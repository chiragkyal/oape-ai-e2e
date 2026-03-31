package main

import (
	"context"
	"fmt"
	"io"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
	"k8s.io/client-go/rest"
	"k8s.io/client-go/tools/clientcmd"
)

// K8sClient wraps a Kubernetes clientset with the target namespace.
type K8sClient struct {
	clientset kubernetes.Interface
	namespace string
}

// NewK8sClient creates a Kubernetes client using in-cluster config,
// falling back to KUBECONFIG for local development.
func NewK8sClient(namespace string) (*K8sClient, error) {
	config, err := rest.InClusterConfig()
	if err != nil {
		// Fall back to kubeconfig for local dev.
		config, err = clientcmd.BuildConfigFromFlags("", clientcmd.RecommendedHomeFile)
		if err != nil {
			return nil, fmt.Errorf("building k8s config: %w", err)
		}
	}

	clientset, err := kubernetes.NewForConfig(config)
	if err != nil {
		return nil, fmt.Errorf("creating k8s clientset: %w", err)
	}

	return &K8sClient{clientset: clientset, namespace: namespace}, nil
}

// WorkflowParams holds the parameters needed to create a workflow K8s Job.
type WorkflowParams struct {
	GHToken          string
	EPUrl            string
	Repo             string
	WorkerImage      string
	EnvConfigMap     string
	GCloudSecret     string
	ConfigsConfigMap string
	TTLAfterFinished int32
}

// CreateWorkflowJob creates a Kubernetes Job for a workflow run.
func (c *K8sClient) CreateWorkflowJob(ctx context.Context, jobID string, params WorkflowParams) error {
	jobName := "oape-workflow-" + jobID
	backoffLimit := int32(0)
	ttl := params.TTLAfterFinished

	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name: jobName,
			Labels: map[string]string{
				"app":    "oape-worker",
				"job-id": jobID,
			},
		},
		Spec: batchv1.JobSpec{
			BackoffLimit:            &backoffLimit,
			TTLSecondsAfterFinished: &ttl,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{
						"app":    "oape-worker",
						"job-id": jobID,
					},
				},
				Spec: corev1.PodSpec{
					RestartPolicy: corev1.RestartPolicyNever,
					Containers: []corev1.Container{
						{
							Name:    "worker",
							Image:   params.WorkerImage,
							Command: []string{"sh", "-c", "gh auth setup-git && python3.11 /app/main.py"},
							Env: []corev1.EnvVar{
								{Name: "GH_TOKEN", Value: params.GHToken},
								{Name: "EP_URL", Value: params.EPUrl},
								{Name: "REPO", Value: params.Repo},
								{Name: "PYTHONUNBUFFERED", Value: "1"},
								{Name: "GOOGLE_APPLICATION_CREDENTIALS", Value: "/secrets/gcloud/application_default_credentials.json"},
								{Name: "GIT_AUTHOR_NAME", Value: "openshift-app-platform-shift-bot"},
								{Name: "GIT_COMMITTER_NAME", Value: "openshift-app-platform-shift-bot"},
								{Name: "GIT_AUTHOR_EMAIL", Value: "267347085+openshift-app-platform-shift-bot@users.noreply.github.com"},
								{Name: "GIT_COMMITTER_EMAIL", Value: "267347085+openshift-app-platform-shift-bot@users.noreply.github.com"},
							},
							EnvFrom: []corev1.EnvFromSource{
								{
									ConfigMapRef: &corev1.ConfigMapEnvSource{
										LocalObjectReference: corev1.LocalObjectReference{
											Name: params.EnvConfigMap,
										},
									},
								},
							},
							VolumeMounts: []corev1.VolumeMount{
								{
									Name:      "gcloud-adc",
									MountPath: "/secrets/gcloud",
									ReadOnly:  true,
								},
								{
									Name:      "config",
									MountPath: "/config",
									ReadOnly:  true,
								},
							},
						},
					},
					Volumes: []corev1.Volume{
						{
							Name: "gcloud-adc",
							VolumeSource: corev1.VolumeSource{
								Secret: &corev1.SecretVolumeSource{
									SecretName: params.GCloudSecret,
								},
							},
						},
						{
							Name: "config",
							VolumeSource: corev1.VolumeSource{
								ConfigMap: &corev1.ConfigMapVolumeSource{
									LocalObjectReference: corev1.LocalObjectReference{
										Name: params.ConfigsConfigMap,
									},
								},
							},
						},
					},
				},
			},
		},
	}

	_, err := c.clientset.BatchV1().Jobs(c.namespace).Create(ctx, job, metav1.CreateOptions{})
	if err != nil {
		return fmt.Errorf("creating job %s: %w", jobName, err)
	}
	return nil
}

// JobStatus represents the current state of a workflow job.
type JobStatus struct {
	Status  string `json:"status"`
	Message string `json:"message,omitempty"`
}

// GetJobStatus returns the status of a workflow K8s Job.
func (c *K8sClient) GetJobStatus(ctx context.Context, jobID string) (*JobStatus, error) {
	jobName := "oape-workflow-" + jobID
	job, err := c.clientset.BatchV1().Jobs(c.namespace).Get(ctx, jobName, metav1.GetOptions{})
	if err != nil {
		return nil, fmt.Errorf("getting job %s: %w", jobName, err)
	}

	for _, cond := range job.Status.Conditions {
		if cond.Type == batchv1.JobComplete && cond.Status == corev1.ConditionTrue {
			return &JobStatus{Status: "succeeded"}, nil
		}
		if cond.Type == batchv1.JobFailed && cond.Status == corev1.ConditionTrue {
			return &JobStatus{Status: "failed", Message: cond.Message}, nil
		}
	}

	if job.Status.Active > 0 {
		return &JobStatus{Status: "running"}, nil
	}

	return &JobStatus{Status: "pending"}, nil
}

// GetJobPod returns the name of the pod created by a workflow Job.
func (c *K8sClient) GetJobPod(ctx context.Context, jobID string) (string, error) {
	jobName := "oape-workflow-" + jobID
	pods, err := c.clientset.CoreV1().Pods(c.namespace).List(ctx, metav1.ListOptions{
		LabelSelector: "job-name=" + jobName,
	})
	if err != nil {
		return "", fmt.Errorf("listing pods for job %s: %w", jobName, err)
	}
	if len(pods.Items) == 0 {
		return "", fmt.Errorf("no pods found for job %s", jobName)
	}
	return pods.Items[0].Name, nil
}

// StreamPodLogs returns a streaming reader of pod logs.
func (c *K8sClient) StreamPodLogs(ctx context.Context, podName string, follow bool) (io.ReadCloser, error) {
	req := c.clientset.CoreV1().Pods(c.namespace).GetLogs(podName, &corev1.PodLogOptions{
		Follow: follow,
	})
	return req.Stream(ctx)
}
