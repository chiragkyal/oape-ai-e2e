# oape-review-handler Prow Setup

Reference documentation for the `oape-review-handler` CI step. This file is **not consumed by CI directly** — it describes how the step is built, registered, and onboarded.

## Architecture

1. Image built from [`images/review-handler.Dockerfile`](../images/review-handler.Dockerfile) in oape-ai-e2e
2. Promoted via oape-ai-e2e's ci-operator config (namespace: `oape`, name: `ai-e2e-agent`, tag: `review-handler-agent`)
3. Consumed by a step-registry ref: `oape-review-handler`
4. Operators onboard by adding `- ref: oape-review-handler` to their test config

## Trigger

On any PR in an onboarded repo:

```
/test oape-review-handler
```

For rehearsal (from an openshift/release PR):

```
/pj-rehearse oape-review-handler
```

## Step 1: Image build (this repo)

The image is added to the oape-ai-e2e ci-operator config:

```yaml
images:
  items:
  - dockerfile_path: images/review-handler.Dockerfile
    to: review-handler-agent
```

Promotion config (already in `openshift-eng-oape-ai-e2e-main.yaml`):

```yaml
promotion:
  to:
  - name: ai-e2e-agent
    namespace: oape
    tag_by_commit: true
```

## Step 2: Step registry ref

Location: `ci-operator/step-registry/oape/review-handler/`

`oape-review-handler-ref.yaml`:

```yaml
ref:
  as: oape-review-handler
  from_image:
    namespace: oape
    name: ai-e2e-agent
    tag: review-handler-agent
  commands: oape-review-handler-commands.sh
  credentials:
  - mount_path: /var/run/gcloud-adc
    name: oap-lts-claude-gcp-vertex-sa
    namespace: test-credentials
  - mount_path: /var/run/github-app
    name: openshift-app-platform-shift-github-bot
    namespace: test-credentials
  timeout: 1h0m0s
  resources:
    requests:
      cpu: "1"
      memory: 500Mi
  documentation: |-
    Fetch unresolved PR review threads and apply AI-assisted fixes/replies
    via oape review-handler.
```

## Step 3: Operator onboarding

Example: must-gather-operator. In the operator's ci-operator config, add:

```yaml
- always_run: false
  as: oape-review-handler
  optional: true
  steps:
    test:
    - ref: oape-review-handler
```

Then run `make jobs` to regenerate presubmits.
