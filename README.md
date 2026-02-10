# oape-ai-e2e

AI-driven Feature Development tools.

## Installation

Add the marketplace:
```shell
/plugin marketplace add chiragkyal/oape-ai-e2e
```

Install the plugin:
```shell
/plugin install oape@oape-ai-e2e
```

Use the commands:
```shell
/oape:api-generate https://github.com/openshift/enhancements/pull/1234
```

## Updating Plugins

Update the marketplace (fetches latest plugin catalog):
```shell
/plugin marketplace update oape-ai-e2e
```

Reinstall the plugin (downloads new version):
```shell
/plugin install oape@oape-ai-e2e
```

## Using Cursor

Cursor can discover the commands by symlinking this repo into your `~/.cursor/commands` directory:

```bash
mkdir -p ~/.cursor/commands
git clone git@github.com:chiragkyal/oape-ai-e2e.git
ln -s oape-ai-e2e ~/.cursor/commands/oape-ai-e2e
```

## Available Plugins

| Plugin                    | Description                                    | Commands                                     |
| ------------------------- | ---------------------------------------------- | -------------------------------------------- |
| **[oape](plugins/oape/)** | AI-driven OpenShift operator development tools | `/oape:api-generate`, `/oape:api-implement`  |

## Commands

### `/oape:api-generate` -- Generate API Types from Enhancement Proposal

Reads an OpenShift enhancement proposal PR, extracts the required API changes, and generates compliant Go type definitions in the correct paths of the current OpenShift operator repository.

```shell
/oape:api-generate https://github.com/openshift/enhancements/pull/1234
```

### `/oape:api-implement` -- Generate Controller Implementation from Enhancement Proposal

Reads an OpenShift enhancement proposal PR, extracts the required implementation logic, and generates complete controller/reconciler code following controller-runtime and operator-sdk conventions.

```shell
/oape:api-implement https://github.com/openshift/enhancements/pull/1234
```

**Typical workflow:**
```shell
# Step 1: Generate API types
/oape:api-generate https://github.com/openshift/enhancements/pull/1234

# Step 2: Generate controller implementation
/oape:api-implement https://github.com/openshift/enhancements/pull/1234
```

### Adding a New Command

1. Add a new markdown file under `plugins/oape/commands/`
2. The command will be available as `/oape:<command-name>`
3. Update the plugin `README.md` documenting the new command

### Plugin Structure

```text
plugins/oape/
├── .claude-plugin/
│   └── plugin.json           # Required: plugin metadata
├── commands/
│   └── <command-name>.md     # Slash commands
├── skills/
│   └── <skill-name>/
│       └── SKILL.md          # Reusable agent skills (optional)
└── README.md                 # Plugin documentation
```
