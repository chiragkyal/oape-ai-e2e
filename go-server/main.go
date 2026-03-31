package main

import (
	"log"
	"net/http"
)

func main() {
	cfg, err := LoadConfig()
	if err != nil {
		log.Fatalf("failed to load config: %v", err)
	}

	k8s, err := NewK8sClient(cfg.JobNamespace)
	if err != nil {
		log.Fatalf("failed to create k8s client: %v", err)
	}

	app := &App{
		cfg: cfg,
		k8s: k8s,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /", app.HandleHome)
	mux.HandleFunc("GET /repos", app.HandleRepos)
	mux.HandleFunc("POST /submit", app.HandleSubmit)
	mux.HandleFunc("GET /status/{job_id}", app.HandleStatus)
	mux.HandleFunc("GET /stream/{job_id}", app.HandleStream)

	log.Printf("Orchestrator listening on %s", cfg.ListenAddr)
	log.Fatal(http.ListenAndServe(cfg.ListenAddr, mux))
}
