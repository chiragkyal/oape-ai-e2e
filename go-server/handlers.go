package main

import (
	"bufio"
	"crypto/rand"
	"embed"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"regexp"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

//go:embed static/homepage.html
var staticFS embed.FS

// App holds shared dependencies for HTTP handlers.
type App struct {
	cfg *ServerConfig
	k8s *K8sClient
}

var epURLPattern = regexp.MustCompile(`^https://github\.com/openshift/enhancements/pull/\d+/?$`)

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	json.NewEncoder(w).Encode(v)
}

func writeError(w http.ResponseWriter, code int, msg string) {
	writeJSON(w, code, map[string]string{"detail": msg})
}

func generateJobID() (string, error) {
	b := make([]byte, 6)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

// HandleHome serves the UI.
func (a *App) HandleHome(w http.ResponseWriter, r *http.Request) {
	data, err := staticFS.ReadFile("static/homepage.html")
	if err != nil {
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write(data)
}

// HandleRepos returns the list of allowed repositories.
func (a *App) HandleRepos(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"repositories": a.cfg.TeamRepos,
	})
}

// fetchToken calls the Token Service to get an ephemeral GitHub token.
func (a *App) fetchToken() (string, error) {
	resp, err := http.Get(a.cfg.TokenServiceURL + "/token")
	if err != nil {
		return "", fmt.Errorf("calling token service: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", fmt.Errorf("token service returned %d: %s", resp.StatusCode, body)
	}

	var result struct {
		Token string `json:"token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("decoding token response: %w", err)
	}
	return result.Token, nil
}

// HandleSubmit creates a K8s Job for a workflow run.
func (a *App) HandleSubmit(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil {
		writeError(w, http.StatusBadRequest, "invalid form data")
		return
	}

	epURL := r.FormValue("ep_url")
	repo := r.FormValue("repo")

	if epURL == "" || repo == "" {
		writeError(w, http.StatusBadRequest, "ep_url and repo are required")
		return
	}

	if !epURLPattern.MatchString(epURL) {
		writeError(w, http.StatusBadRequest, "ep_url must be a valid OpenShift enhancement PR URL")
		return
	}

	if a.cfg.FindRepo(repo) == nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unknown repository: %s", repo))
		return
	}

	token, err := a.fetchToken()
	if err != nil {
		log.Printf("ERROR: fetching token: %v", err)
		writeError(w, http.StatusInternalServerError, "failed to generate GitHub token")
		return
	}

	jobID, err := generateJobID()
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to generate job ID")
		return
	}

	params := WorkflowParams{
		GHToken:          token,
		EPUrl:            epURL,
		Repo:             repo,
		WorkerImage:      a.cfg.WorkerImage,
		EnvConfigMap:     a.cfg.WorkerEnvConfigMap,
		GCloudSecret:     a.cfg.GCloudSecretName,
		ConfigsConfigMap: a.cfg.ConfigsConfigMap,
		TTLAfterFinished: a.cfg.TTLAfterFinished,
	}

	if err := a.k8s.CreateWorkflowJob(r.Context(), jobID, params); err != nil {
		log.Printf("ERROR: creating job: %v", err)
		writeError(w, http.StatusInternalServerError, "failed to create workflow job")
		return
	}

	log.Printf("Created workflow job %s for ep=%s repo=%s", jobID, epURL, repo)
	writeJSON(w, http.StatusOK, map[string]string{"job_id": jobID})
}

// HandleStatus returns the status of a workflow job.
func (a *App) HandleStatus(w http.ResponseWriter, r *http.Request) {
	jobID := r.PathValue("job_id")
	if jobID == "" {
		writeError(w, http.StatusBadRequest, "job_id is required")
		return
	}

	status, err := a.k8s.GetJobStatus(r.Context(), jobID)
	if err != nil {
		writeError(w, http.StatusNotFound, fmt.Sprintf("job not found: %s", jobID))
		return
	}

	writeJSON(w, http.StatusOK, status)
}

// HandleStream streams pod logs as SSE events.
func (a *App) HandleStream(w http.ResponseWriter, r *http.Request) {
	jobID := r.PathValue("job_id")
	if jobID == "" {
		writeError(w, http.StatusBadRequest, "job_id is required")
		return
	}

	flusher, ok := w.(http.Flusher)
	if !ok {
		http.Error(w, "streaming not supported", http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")

	ctx := r.Context()

	// Wait for the pod to be available (up to 5 minutes).
	var podName string
	deadline := time.Now().Add(5 * time.Minute)
	for {
		if time.Now().After(deadline) {
			fmt.Fprintf(w, "event: complete\ndata: %s\n\n",
				`{"status":"failed","message":"timed out waiting for pod"}`)
			flusher.Flush()
			return
		}

		select {
		case <-ctx.Done():
			return
		default:
		}

		name, err := a.k8s.GetJobPod(ctx, jobID)
		if err == nil {
			podName = name
			break
		}

		fmt.Fprintf(w, "event: status\ndata: %s\n\n",
			`{"status":"waiting_for_pod"}`)
		flusher.Flush()

		select {
		case <-ctx.Done():
			return
		case <-time.After(2 * time.Second):
		}
	}

	// Wait for pod to be running or terminated.
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		pod, err := a.k8s.clientset.CoreV1().Pods(a.k8s.namespace).Get(ctx, podName, metav1.GetOptions{})
		if err != nil {
			fmt.Fprintf(w, "event: status\ndata: %s\n\n",
				`{"status":"waiting_for_pod"}`)
			flusher.Flush()
			time.Sleep(2 * time.Second)
			continue
		}

		phase := pod.Status.Phase
		if phase == corev1.PodRunning || phase == corev1.PodSucceeded || phase == corev1.PodFailed {
			break
		}

		fmt.Fprintf(w, "event: status\ndata: %s\n\n",
			fmt.Sprintf(`{"status":"pod_%s"}`, string(phase)))
		flusher.Flush()

		select {
		case <-ctx.Done():
			return
		case <-time.After(2 * time.Second):
		}
	}

	// Stream pod logs.
	logStream, err := a.k8s.StreamPodLogs(ctx, podName, true)
	if err != nil {
		log.Printf("ERROR: streaming logs for pod %s: %v", podName, err)
		fmt.Fprintf(w, "event: complete\ndata: %s\n\n",
			`{"status":"failed","message":"failed to stream logs"}`)
		flusher.Flush()
		return
	}
	defer logStream.Close()

	scanner := bufio.NewScanner(logStream)
	// Increase scanner buffer for long log lines.
	scanner.Buffer(make([]byte, 0, 64*1024), 1024*1024)

	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return
		default:
		}

		line := scanner.Text()
		fmt.Fprintf(w, "event: log\ndata: %s\n\n", line)
		flusher.Flush()
	}

	// Log stream ended — get final job status.
	status, err := a.k8s.GetJobStatus(ctx, jobID)
	if err != nil {
		fmt.Fprintf(w, "event: complete\ndata: %s\n\n",
			`{"status":"unknown","message":"could not determine final status"}`)
	} else {
		data, _ := json.Marshal(status)
		fmt.Fprintf(w, "event: complete\ndata: %s\n\n", data)
	}
	flusher.Flush()
}
