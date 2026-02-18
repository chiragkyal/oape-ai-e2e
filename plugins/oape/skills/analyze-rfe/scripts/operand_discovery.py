#!/usr/bin/env python3
"""
Operand Discovery Module
Discovers operands managed by OpenShift operators
"""

import json
import re
import subprocess
from typing import List, Dict, Optional
from pathlib import Path


class OperandDiscovery:
    """Discovers operands managed by an operator"""

    def __init__(self, cache_dir: Optional[str] = None):
        """Initialize operand discovery"""
        self.cache_dir = Path(cache_dir) if cache_dir else Path(".work/jira/analyze-rfe/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _run_gh_command(self, args: List[str], cache_key: Optional[str] = None) -> Optional[str]:
        """Run gh CLI command with optional caching"""
        if cache_key:
            cache_file = self.cache_dir / f"{cache_key}.json"
            if cache_file.exists():
                return cache_file.read_text()

        try:
            result = subprocess.run(
                ["gh"] + args,
                capture_output=True,
                text=True,
                timeout=30,
                check=False
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if cache_key and output:
                    cache_file = self.cache_dir / f"{cache_key}.json"
                    cache_file.write_text(output)
                return output
            else:
                return None

        except (subprocess.TimeoutExpired, Exception):
            return None

    def is_operator(self, repo_name: str, structure_data: Dict) -> bool:
        """
        Determine if repository is an operator

        Args:
            repo_name: Repository name
            structure_data: Codebase structure from github_repo_analyzer

        Returns:
            True if this is an operator repository
        """
        # Check 1: Name contains "operator"
        if "operator" in repo_name.lower():
            return True

        # Check 2: Architecture is Kubernetes Operator
        if structure_data.get("architecture") == "Kubernetes Operator":
            return True

        # Check 3: Has operator-sdk markers
        # Look for operator-sdk in go.mod or Makefile
        go_mod = self._run_gh_command(
            ["api", f"repos/{repo_name}/contents/go.mod", "--raw"],
            cache_key=f"gomod_{repo_name.replace('/', '_')}"
        )
        if go_mod and "operator-sdk" in go_mod:
            return True

        return False

    def discover_operands(self, operator_repo_name: str) -> List[Dict]:
        """
        Discover operands managed by an operator

        Args:
            operator_repo_name: Operator repository name

        Returns:
            List of operand information dicts
        """
        operands = []

        # Strategy 1: Image references from assets/manifests (most reliable)
        image_operands = self._extract_from_image_references(operator_repo_name)
        operands.extend(image_operands)

        # Strategy 2: Deployment manifests
        manifest_operands = self._extract_from_manifests(operator_repo_name)
        operands.extend(manifest_operands)

        # Strategy 3: OLM ClusterServiceVersion (CSV)
        csv_operands = self._extract_from_csv(operator_repo_name)
        operands.extend(csv_operands)

        # Strategy 4: README analysis
        readme_operands = self._extract_from_readme(operator_repo_name)
        operands.extend(readme_operands)

        # Deduplicate by name (prioritize earlier strategies)
        unique_operands = {}
        for operand in operands:
            name = operand.get("name", "").lower()
            if name and name not in unique_operands:
                unique_operands[name] = operand

        return list(unique_operands.values())

    def _extract_from_image_references(self, repo_name: str) -> List[Dict]:
        """
        Extract operands from container image references in asset files

        This is the most reliable method as it finds the actual operand images
        being deployed by the operator.

        Args:
            repo_name: Repository name

        Returns:
            List of operand dicts
        """
        operands = []

        # Common directories containing deployment assets
        asset_paths = [
            "assets",
            "manifests",
            "deploy",
            "config/manifests",
            "bundle/manifests"
        ]

        for path in asset_paths:
            # Get all YAML files in this directory
            files_data = self._run_gh_command(
                ["api", f"repos/{repo_name}/contents/{path}",
                 "--jq", ".[] | select(.name | endswith(\".yaml\") or endswith(\".yml\")) | .name"],
                cache_key=f"assets_{repo_name.replace('/', '_')}_{path.replace('/', '_')}"
            )

            if not files_data:
                continue

            for filename in files_data.strip().split('\n'):
                if not filename:
                    continue

                # Get file content
                file_content = self._run_gh_command(
                    ["api", f"repos/{repo_name}/contents/{path}/{filename}", "--jq", ".content"],
                    cache_key=f"asset_file_{repo_name.replace('/', '_')}_{path.replace('/', '_')}_{filename}"
                )

                if file_content:
                    try:
                        import base64
                        content = base64.b64decode(file_content.strip()).decode('utf-8')
                    except Exception:
                        continue

                    # Extract image references
                    # Pattern matches: image: registry.io/org/image-name:tag
                    image_patterns = [
                        # Standard image field
                        r'image:\s*["\']?(?:.*?/)?([a-zA-Z0-9][a-zA-Z0-9_-]+):',
                        # Quay.io images
                        r'quay\.io/[^/]+/([a-zA-Z0-9][a-zA-Z0-9_-]+):',
                        # registry.k8s.io images
                        r'registry\.k8s\.io/[^/]+/([a-zA-Z0-9][a-zA-Z0-9_-]+):',
                        # gcr.io images
                        r'gcr\.io/[^/]+/([a-zA-Z0-9][a-zA-Z0-9_-]+):',
                    ]

                    for pattern in image_patterns:
                        matches = re.findall(pattern, content)
                        for image_name in matches:
                            # Clean up image name
                            image_name = image_name.strip().lower()

                            # Filter out operator image itself and common base images
                            if self._is_valid_operand_name(image_name) and "operator" not in image_name:
                                operands.append({
                                    "name": image_name,
                                    "source": f"Image reference ({path}/{filename})"
                                })

        return operands

    def _extract_from_readme(self, repo_name: str) -> List[Dict]:
        """Extract operand references from README"""
        # Use gh api to get README content
        readme_data = self._run_gh_command(
            ["api", f"repos/{repo_name}/readme", "--jq", ".content"],
            cache_key=f"readme_operands_{repo_name.replace('/', '_')}"
        )

        if not readme_data:
            return []

        try:
            # Decode base64
            import base64
            readme_text = base64.b64decode(readme_data).decode('utf-8')
        except Exception:
            return []

        operands = []

        # Pattern 1: "manages X, Y, and Z" or "manages and updates X"
        # More specific: 1-3 hyphenated words, stop at punctuation
        manages_pattern = r'manages?\s+(?:the\s+)?([a-z][a-z0-9-]+(?:\s+[a-z][a-z0-9-]+){0,2})(?:\s+stack|\s+deployed|\s+on|,|\.|\s+and\s+|$)'
        matches = re.findall(manages_pattern, readme_text, re.IGNORECASE)
        for match in matches:
            # Remove markdown links but keep the text
            match = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', match)
            comp = match.strip()
            comp = re.sub(r'\s*\(.*?\)\s*', '', comp)  # Remove parenthetical
            comp = re.sub(r'\*+', '', comp)  # Remove markdown bold
            if self._is_valid_operand_name(comp):
                operands.append({
                    "name": comp,
                    "source": "README (manages pattern)"
                })

        # Pattern 2: "deploys X"
        deploys_pattern = r'deploys?\s+(?:the\s+)?([a-zA-Z0-9-]+)'
        matches = re.findall(deploys_pattern, readme_text, re.IGNORECASE)
        for match in matches:
            if self._is_valid_operand_name(match):
                operands.append({
                    "name": match,
                    "source": "README (deploys pattern)"
                })

        # Pattern 3: "operand" mentions
        operand_pattern = r'operands?[:\s]+([a-zA-Z0-9-,\s]+)'
        matches = re.findall(operand_pattern, readme_text, re.IGNORECASE)
        for match in matches:
            components = re.split(r'[,\s]+', match)
            for comp in components:
                comp = comp.strip()
                if self._is_valid_operand_name(comp):
                    operands.append({
                        "name": comp,
                        "source": "README (operand mention)"
                    })

        # Pattern 4: Markdown list items with component names
        # Only match technical component names (hyphenated, lowercase after first char)
        # Rejects single words like "Manager", "Support", "When"
        list_pattern = r'^\s*[\*\-]\s+\[?([A-Z][a-z]+(?:-[a-z]+)+)\]?\(?'
        for line in readme_text.split('\n'):
            match = re.match(list_pattern, line)
            if match:
                comp = match.group(1)
                # Filter out common non-operand words
                if self._is_valid_operand_name(comp.lower()) and not comp in ['GitHub', 'OpenShift', 'Kubernetes']:
                    operands.append({
                        "name": comp.lower().replace('_', '-'),
                        "source": "README (list item)"
                    })

        return operands

    def _extract_from_manifests(self, repo_name: str) -> List[Dict]:
        """Extract operands from deployment manifests"""
        operands = []

        # Common manifest directories
        manifest_paths = [
            "manifests",
            "deploy",
            "config/manifests",
            "bundle/manifests"
        ]

        for path in manifest_paths:
            files_data = self._run_gh_command(
                ["api", f"repos/{repo_name}/contents/{path}",
                 "--jq", ".[] | select(.name | endswith(\".yaml\") or endswith(\".yml\")) | .name"],
                cache_key=f"manifests_{repo_name.replace('/', '_')}_{path.replace('/', '_')}"
            )

            if not files_data:
                continue

            # For each manifest file, try to extract image references
            for filename in files_data.split('\n'):
                if not filename:
                    continue

                # Get file content
                file_content = self._run_gh_command(
                    ["api", f"repos/{repo_name}/contents/{path}/{filename}", "--raw"],
                    cache_key=f"manifest_file_{repo_name.replace('/', '_')}_{filename}"
                )

                if file_content:
                    # Extract image references
                    image_pattern = r'image:\s*["\']?(?:.*?/)?([a-zA-Z0-9-]+):.*["\']?'
                    images = re.findall(image_pattern, file_content)
                    for image in images:
                        if self._is_valid_operand_name(image):
                            operands.append({
                                "name": image,
                                "source": f"Manifest ({path}/{filename})"
                            })

        return operands

    def _extract_from_csv(self, repo_name: str) -> List[Dict]:
        """Extract operands from OLM ClusterServiceVersion"""
        operands = []

        # Look for CSV files
        csv_paths = [
            "manifests",
            "bundle/manifests",
            "deploy/olm-catalog"
        ]

        for path in csv_paths:
            csv_files = self._run_gh_command(
                ["api", f"repos/{repo_name}/contents/{path}",
                 "--jq", ".[] | select(.name | contains(\"clusterserviceversion\")) | .name"],
                cache_key=f"csv_{repo_name.replace('/', '_')}_{path.replace('/', '_')}"
            )

            if not csv_files:
                continue

            for csv_file in csv_files.split('\n'):
                if not csv_file:
                    continue

                # Get CSV content
                csv_content = self._run_gh_command(
                    ["api", f"repos/{repo_name}/contents/{path}/{csv_file}", "--raw"],
                    cache_key=f"csv_file_{repo_name.replace('/', '_')}_{csv_file}"
                )

                if csv_content:
                    # Extract deployments from CSV
                    deployment_pattern = r'name:\s*([a-zA-Z0-9-]+)'
                    deployments = re.findall(deployment_pattern, csv_content)
                    for deployment in deployments:
                        if self._is_valid_operand_name(deployment):
                            operands.append({
                                "name": deployment,
                                "source": f"OLM CSV ({csv_file})"
                            })

        return operands

    def _is_valid_operand_name(self, name: str) -> bool:
        """Check if a string is a valid operand name"""
        if not name:
            return False

        name = name.strip().lower()

        # Must be reasonable length
        if len(name) < 3 or len(name) > 50:
            return False

        # Must be alphanumeric with hyphens and underscores
        if not re.match(r'^[a-z0-9_-]+$', name):
            return False

        # Exclude common words that aren't operands
        exclude_words = [
            # Original exclude words
            "the", "and", "or", "for", "with", "operator", "openshift",
            "kubernetes", "cluster", "version", "release", "image",
            "container", "pod", "deployment", "service", "namespace",
            "based", "platform", "stack", "component", "monitoring",
            "github", "coreos",
            # Common false positives from recent runs
            "this", "when", "being", "management", "support", "enables",
            "centralizes", "make", "run", "access", "fork", "manager",
            "controller", "system", "infrastructure", "resource",
            # Gerunds and verbs
            "managing", "deploying", "running", "supporting", "monitoring"
        ]
        if name in exclude_words:
            return False

        return True

    def _is_likely_operand_repo(self, repo_data: Dict) -> bool:
        """
        Check if repo is likely an actual operand, not random match

        Args:
            repo_data: Repository information dict

        Returns:
            True if repo appears to be a real operand
        """
        description = repo_data.get("description", "").lower()

        # Exclude repos that are clearly not operands
        exclude_keywords = ["documentation", "example", "test", "tutorial", "runbook", "template"]
        if any(kw in description for kw in exclude_keywords):
            return False

        # If description is empty, still consider it (many repos have no description)
        return True

    def enrich_with_repositories(self, operands: List[Dict], org: str = "openshift") -> List[Dict]:
        """
        Enrich operand list with repository information using dynamic discovery

        Args:
            operands: List of operand dicts
            org: GitHub organization to search

        Returns:
            Enriched operand list with repository info
        """
        enriched = []

        for operand in operands:
            operand_name = operand.get("name", "")

            # Try multiple patterns to find the repository
            repo_patterns = [
                # Exact match
                f"{org}/{operand_name}",
                # With common suffixes
                f"{org}/{operand_name}-controller",
                f"{org}/{operand_name}-server",
                f"{org}/{operand_name}-daemon",
                # Handle CSI driver naming
                f"{org}/{operand_name}",  # secrets-store-csi-driver
                # Handle name variations (underscores to hyphens)
                f"{org}/{operand_name.replace('_', '-')}",
            ]

            repo_found = None
            for pattern in repo_patterns:
                repo_data = self._run_gh_command(
                    ["repo", "view", pattern, "--json", "name,url,description"],
                    cache_key=f"operand_repo_{pattern.replace('/', '_')}"
                )

                if repo_data:
                    try:
                        repo_info = json.loads(repo_data)
                        # Validate that this is likely a real operand
                        if self._is_likely_operand_repo(repo_info):
                            repo_found = {
                                "name": pattern,
                                "url": repo_info.get("url"),
                                "description": repo_info.get("description", "")
                            }
                            break
                    except json.JSONDecodeError:
                        continue

            # If not found by exact patterns, try searching
            if not repo_found:
                repo_found = self._search_for_operand_repo(operand_name, org)

            enriched.append({
                **operand,
                "repository": repo_found
            })

        return enriched

    def _search_for_operand_repo(self, operand_name: str, org: str = "openshift") -> Optional[Dict]:
        """
        Search for operand repository when exact patterns don't match

        Args:
            operand_name: Operand name
            org: GitHub organization

        Returns:
            Repository info or None
        """
        # Search in the organization
        search_data = self._run_gh_command(
            ["search", "repos", "--owner", org, operand_name,
             "--json", "name,url,description", "--limit", "3"],
            cache_key=f"operand_search_{org}_{operand_name}"
        )

        if search_data:
            try:
                results = json.loads(search_data)
                if results:
                    # Return first match (most relevant)
                    best_match = results[0]
                    return {
                        "name": f"{org}/{best_match['name']}",
                        "url": best_match.get("url"),
                        "description": best_match.get("description", "")
                    }
            except json.JSONDecodeError:
                pass

        return None


def main():
    """Test operand discovery"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: operand_discovery.py <operator-repo-name>")
        print("\nExample: operand_discovery.py openshift/cert-manager-operator")
        sys.exit(1)

    repo_name = sys.argv[1]

    discovery = OperandDiscovery()

    # Check if it's an operator
    print(f"Checking if {repo_name} is an operator...")
    # We'd need structure data for full check, but skip for this test
    print("(Assuming it's an operator for testing)\n")

    # Discover operands
    print(f"Discovering operands managed by {repo_name}...\n")
    operands = discovery.discover_operands(repo_name)

    print("=" * 70)
    print(f"DISCOVERED OPERANDS ({len(operands)})")
    print("=" * 70)

    if operands:
        for i, operand in enumerate(operands, 1):
            print(f"\n{i}. {operand.get('name')}")
            print(f"   Source: {operand.get('source')}")

        # Enrich with repositories
        print(f"\n{'=' * 70}")
        print("ENRICHING WITH REPOSITORY INFO")
        print("=" * 70)

        enriched = discovery.enrich_with_repositories(operands)
        for operand in enriched:
            print(f"\n{operand.get('name')}:")
            repo = operand.get("repository")
            if repo:
                print(f"  Repository: {repo.get('name')}")
                print(f"  URL: {repo.get('url')}")
                print(f"  Description: {repo.get('description', 'N/A')}")
            else:
                print(f"  Repository: Not found")
    else:
        print("No operands discovered")


if __name__ == "__main__":
    main()
