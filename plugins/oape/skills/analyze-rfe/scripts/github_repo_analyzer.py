#!/usr/bin/env python3
"""
GitHub Repository Analyzer
Discovers and analyzes OpenShift component repositories using GitHub CLI (gh)
"""

import json
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class GitHubRepoAnalyzer:
    """Analyzes GitHub repositories remotely via gh CLI"""

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize the analyzer

        Args:
            cache_dir: Directory to cache API results (default: .work/jira/analyze-rfe/cache)
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path(".work/jira/analyze-rfe/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Check if gh CLI is available
        if not self._check_gh_cli():
            print("Error: GitHub CLI (gh) not found", file=sys.stderr)
            print("Install from: https://cli.github.com/", file=sys.stderr)
            sys.exit(1)

    def _check_gh_cli(self) -> bool:
        """Check if gh CLI is installed and authenticated"""
        try:
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _run_gh_command(self, args: List[str], cache_key: Optional[str] = None) -> Optional[str]:
        """
        Run gh CLI command with optional caching

        Args:
            args: Command arguments
            cache_key: Cache file key (if None, no caching)

        Returns:
            Command output or None on error
        """
        # Check cache first
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
                # Cache successful results
                if cache_key and output:
                    cache_file = self.cache_dir / f"{cache_key}.json"
                    cache_file.write_text(output)
                return output
            else:
                # Not an error, just no results (e.g., repo not found)
                return None

        except subprocess.TimeoutExpired:
            print(f"Warning: Command timed out: gh {' '.join(args)}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"Warning: Command failed: gh {' '.join(args)}: {e}", file=sys.stderr)
            return None

    def discover_repositories(self, component_name: str) -> Dict[str, any]:
        """
        Discover downstream, upstream, and related repositories using dynamic strategies

        Args:
            component_name: Component name (e.g., "cert-manager", "hypershift")

        Returns:
            Dict with downstream, upstream, and related repos
        """
        repos = {
            "component": component_name,
            "downstream": None,
            "upstream": None,
            "related": []
        }

        # Step 1: Find downstream repository
        repos["downstream"] = self._find_downstream_repo(component_name)

        # Step 2: Find upstream repository (multiple strategies)
        if repos["downstream"]:
            downstream_name = repos["downstream"]["name"]

            # Strategy 1: Check if repo is a fork
            upstream = self._find_upstream_via_fork(downstream_name)
            if upstream:
                repos["upstream"] = upstream

            # Strategy 2: Parse go.mod for upstream dependencies
            if not repos["upstream"]:
                upstream = self._find_upstream_via_gomod(downstream_name, component_name)
                if upstream:
                    repos["upstream"] = upstream

            # Strategy 3: Parse README for upstream references
            if not repos["upstream"]:
                upstream = self._find_upstream_via_readme(downstream_name)
                if upstream:
                    repos["upstream"] = upstream

            # Strategy 4: Search common upstream orgs
            if not repos["upstream"]:
                upstream = self._find_upstream_via_search(component_name)
                if upstream:
                    repos["upstream"] = upstream

        # Step 3: Search for related repos
        related = self._search_related_repos(component_name)
        repos["related"] = related

        return repos

    def _find_downstream_repo(self, component_name: str) -> Optional[Dict]:
        """
        Find downstream OpenShift repository using common patterns

        Args:
            component_name: Component name

        Returns:
            Downstream repo info or None
        """
        # Try common OpenShift repo patterns
        patterns = [
            component_name,
            f"{component_name}-operator",
            f"cluster-{component_name}-operator",
            f"{component_name}-controller",
            f"{component_name}-csi-driver-operator",
            # Handle names with "csi" variations
            component_name.replace("-csi", "-csi-driver-operator"),
            component_name.replace("-csi", "s-csi-driver-operator"),  # secret-store-csi -> secrets-store-csi-driver-operator
        ]

        for pattern in patterns:
            repo_data = self._run_gh_command(
                ["repo", "view", f"openshift/{pattern}", "--json", "name,url,description,defaultBranchRef,isFork,parent"],
                cache_key=f"repo_openshift_{pattern}"
            )

            if repo_data:
                try:
                    repo_info = json.loads(repo_data)
                    return {
                        "name": f"openshift/{pattern}",
                        "url": repo_info.get("url"),
                        "description": repo_info.get("description", ""),
                        "default_branch": repo_info.get("defaultBranchRef", {}).get("name", "main"),
                        "is_fork": repo_info.get("isFork", False),
                        "parent": repo_info.get("parent")
                    }
                except json.JSONDecodeError:
                    continue

        return None

    def _find_upstream_via_fork(self, repo_name: str) -> Optional[Dict]:
        """
        Find upstream by checking if repo is a GitHub fork

        Args:
            repo_name: Repository name (e.g., "openshift/secrets-store-csi-driver-operator")

        Returns:
            Upstream repo info or None
        """
        repo_data = self._run_gh_command(
            ["repo", "view", repo_name, "--json", "isFork,parent"],
            cache_key=f"fork_check_{repo_name.replace('/', '_')}"
        )

        if repo_data:
            try:
                repo_info = json.loads(repo_data)
                if repo_info.get("isFork") and repo_info.get("parent"):
                    parent = repo_info["parent"]
                    return {
                        "name": parent.get("nameWithOwner"),
                        "url": parent.get("url"),
                        "description": parent.get("description", ""),
                        "discovery_method": "GitHub fork parent"
                    }
            except json.JSONDecodeError:
                pass

        return None

    def _find_upstream_via_gomod(self, repo_name: str, component_name: str) -> Optional[Dict]:
        """
        Find upstream by parsing go.mod for dependencies

        Args:
            repo_name: Repository name
            component_name: Component name to look for

        Returns:
            Upstream repo info or None
        """
        # Get go.mod content
        gomod_data = self._run_gh_command(
            ["api", f"repos/{repo_name}/contents/go.mod", "--jq", ".content"],
            cache_key=f"gomod_{repo_name.replace('/', '_')}"
        )

        if not gomod_data:
            return None

        try:
            # Decode base64
            import base64
            gomod_content = base64.b64decode(gomod_data.strip()).decode('utf-8')
        except Exception:
            return None

        # Look for upstream dependencies
        # Pattern: github.com/org/repo v1.2.3
        import re

        # Common upstream orgs for OpenShift components
        upstream_orgs = [
            "kubernetes-sigs",
            "kubernetes",
            "cert-manager",
            "prometheus-operator",
            "external-secrets",
            "coredns",
            "etcd-io",
            "envoyproxy",
            "grafana",
        ]

        # Normalize component name for matching
        component_normalized = component_name.lower().replace("-operator", "").replace("cluster-", "")

        for org in upstream_orgs:
            # Pattern 1: Exact match on component name
            pattern1 = rf'github\.com/{org}/([a-zA-Z0-9_-]*{re.escape(component_normalized)}[a-zA-Z0-9_-]*)\s'
            match = re.search(pattern1, gomod_content, re.IGNORECASE)

            if match:
                upstream_repo = match.group(1)
                return {
                    "name": f"{org}/{upstream_repo}",
                    "url": f"https://github.com/{org}/{upstream_repo}",
                    "discovery_method": "go.mod dependency"
                }

            # Pattern 2: Look for CSI driver pattern
            if "csi" in component_name.lower():
                pattern2 = rf'github\.com/{org}/([a-zA-Z0-9_-]*csi[a-zA-Z0-9_-]*)\s'
                match = re.search(pattern2, gomod_content, re.IGNORECASE)

                if match:
                    upstream_repo = match.group(1)
                    return {
                        "name": f"{org}/{upstream_repo}",
                        "url": f"https://github.com/{org}/{upstream_repo}",
                        "discovery_method": "go.mod CSI dependency"
                    }

        return None

    def _find_upstream_via_readme(self, repo_name: str) -> Optional[Dict]:
        """
        Find upstream by parsing README for references

        Args:
            repo_name: Repository name

        Returns:
            Upstream repo info or None
        """
        readme_data = self._run_gh_command(
            ["api", f"repos/{repo_name}/readme", "--jq", ".content"],
            cache_key=f"readme_upstream_{repo_name.replace('/', '_')}"
        )

        if not readme_data:
            return None

        try:
            import base64
            readme_text = base64.b64decode(readme_data.strip()).decode('utf-8')
        except Exception:
            return None

        # Enhanced upstream detection patterns
        import re
        patterns = [
            # Explicit upstream mentions
            r'upstream[:\s]+(?:https?://)?github\.com/([^/\s]+)/([^/\s\)]+)',
            r'based on[:\s]+(?:https?://)?github\.com/([^/\s]+)/([^/\s\)]+)',
            r'fork of[:\s]+(?:https?://)?github\.com/([^/\s]+)/([^/\s\)]+)',
            r'from[:\s]+(?:https?://)?github\.com/([^/\s]+)/([^/\s\)]+)',
            # Badge links (often point to upstream)
            r'\[!\[.*?\]\(https?://.*?\)\]\(https?://github\.com/([^/\s]+)/([^/\s\)]+)\)',
            # Documentation links
            r'documentation[:\s]+(?:https?://)?github\.com/([^/\s]+)/([^/\s\)]+)',
            # See also / Related projects
            r'see also[:\s]+(?:https?://)?github\.com/([^/\s]+)/([^/\s\)]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, readme_text, re.IGNORECASE)
            if match:
                org, repo = match.groups()
                # Filter out openshift org (we want upstream, not downstream)
                if org.lower() != "openshift":
                    return {
                        "name": f"{org}/{repo}",
                        "url": f"https://github.com/{org}/{repo}",
                        "discovery_method": "README reference"
                    }

        return None

    def _find_upstream_via_search(self, component_name: str) -> Optional[Dict]:
        """
        Find upstream by searching common upstream organizations

        Args:
            component_name: Component name

        Returns:
            Upstream repo info or None
        """
        # Common upstream orgs in priority order
        upstream_orgs = [
            "kubernetes-sigs",
            "kubernetes",
            "cert-manager",
            "prometheus-operator",
            "external-secrets",
        ]

        # Normalize component name
        search_term = component_name.lower().replace("-operator", "").replace("cluster-", "")

        for org in upstream_orgs:
            search_data = self._run_gh_command(
                ["search", "repos", "--owner", org, search_term,
                 "--json", "name,description,url,stargazersCount", "--limit", "3"],
                cache_key=f"upstream_search_{org}_{search_term}"
            )

            if search_data:
                try:
                    results = json.loads(search_data)
                    if results:
                        # Return the most starred result (likely the main project)
                        best_match = max(results, key=lambda r: r.get("stargazersCount", 0))
                        return {
                            "name": f"{org}/{best_match['name']}",
                            "url": best_match.get("url"),
                            "description": best_match.get("description", ""),
                            "discovery_method": f"GitHub search in {org}"
                        }
                except json.JSONDecodeError:
                    continue

        return None


    def _search_related_repos(self, component_name: str, limit: int = 5) -> List[Dict]:
        """Search for related repositories in openshift org"""
        search_data = self._run_gh_command(
            ["search", "repos", "--owner", "openshift", component_name,
             "--json", "name,description,url", "--limit", str(limit)],
            cache_key=f"search_repos_{component_name}"
        )

        if not search_data:
            return []

        try:
            results = json.loads(search_data)
            return [
                {
                    "name": f"openshift/{r['name']}",
                    "url": r.get("url"),
                    "description": r.get("description", "")
                }
                for r in results
            ]
        except json.JSONDecodeError:
            return []

    def analyze_codebase_structure(self, repo_name: str) -> Dict[str, any]:
        """
        Analyze repository structure to determine architecture and key components

        Args:
            repo_name: Full repo name (e.g., "openshift/cert-manager-operator")

        Returns:
            Dict with architecture type, key packages, API types
        """
        structure = {
            "architecture": "Unknown",
            "key_packages": [],
            "api_types": [],
            "controllers": []
        }

        # Get root directory structure
        root_contents = self._run_gh_command(
            ["api", f"repos/{repo_name}/contents/", "--jq", ".[].name"],
            cache_key=f"root_{repo_name.replace('/', '_')}"
        )

        if not root_contents:
            return structure

        root_files = root_contents.strip().split('\n')

        # Detect architecture pattern
        has_crd = "config" in root_files or any("crd" in f.lower() for f in root_files)
        has_cmd = "cmd" in root_files
        has_pkg = "pkg" in root_files
        has_dockerfile = any("dockerfile" in f.lower() for f in root_files)

        if has_crd:
            structure["architecture"] = "Kubernetes Operator"
            # Get CRDs
            structure["api_types"] = self._extract_crds(repo_name)
            # Get controllers
            structure["controllers"] = self._find_controllers(repo_name)
        elif has_cmd and has_pkg:
            structure["architecture"] = "CLI Tool / Binary"
        elif has_pkg and not has_cmd:
            structure["architecture"] = "Library"
        elif has_dockerfile:
            structure["architecture"] = "Containerized Service"

        # Get key packages
        if has_pkg:
            structure["key_packages"] = self._get_key_packages(repo_name)

        return structure

    def _extract_crds(self, repo_name: str) -> List[Dict]:
        """Extract CRD definitions"""
        crd_paths = [
            "config/crd/bases",
            "config/crds",
            "deploy/crds",
        ]

        crds = []
        for path in crd_paths:
            crd_data = self._run_gh_command(
                ["api", f"repos/{repo_name}/contents/{path}", "--jq", ".[] | select(.name | endswith(\".yaml\")) | .name"],
                cache_key=f"crds_{repo_name.replace('/', '_')}_{path.replace('/', '_')}"
            )

            if crd_data:
                crd_files = crd_data.strip().split('\n')
                for crd_file in crd_files:
                    if crd_file:
                        crds.append({
                            "file": crd_file,
                            "path": f"{path}/{crd_file}"
                        })
                break  # Found CRDs, no need to check other paths

        return crds

    def _find_controllers(self, repo_name: str) -> List[str]:
        """Find controller files"""
        pkg_controllers = self._run_gh_command(
            ["api", f"repos/{repo_name}/contents/pkg/controllers", "--jq", ".[].name"],
            cache_key=f"controllers_{repo_name.replace('/', '_')}"
        )

        if pkg_controllers:
            return [c for c in pkg_controllers.strip().split('\n') if c]

        return []

    def _get_key_packages(self, repo_name: str) -> List[Dict]:
        """Get key packages from pkg/ directory"""
        pkg_data = self._run_gh_command(
            ["api", f"repos/{repo_name}/contents/pkg", "--jq", ".[] | select(.type == \"dir\") | {{name: .name, path: .path}}"],
            cache_key=f"pkg_{repo_name.replace('/', '_')}"
        )

        if not pkg_data:
            return []

        packages = []
        for line in pkg_data.strip().split('\n'):
            if line:
                try:
                    pkg = json.loads(line)
                    packages.append(pkg)
                except json.JSONDecodeError:
                    continue

        return packages[:10]  # Limit to top 10

    def get_repository_metadata(self, repo_name: str) -> Dict:
        """Get basic repository metadata"""
        data = self._run_gh_command(
            ["repo", "view", repo_name, "--json",
             "name,description,url,defaultBranchRef,languages,stargazerCount,createdAt,updatedAt"],
            cache_key=f"metadata_{repo_name.replace('/', '_')}"
        )

        if data:
            try:
                return json.loads(data)
            except json.JSONDecodeError:
                pass

        return {}

    def find_rfe_related_files(self, repo_name: str, rfe_keywords: List[str]) -> Dict:
        """
        Find files related to RFE by searching code for specific patterns

        Args:
            repo_name: Repository name
            rfe_keywords: Keywords from RFE description

        Returns:
            Dict with categorized file findings
        """
        results = {
            "flag_definitions": [],
            "crd_definitions": [],
            "config_files": [],
            "controller_files": [],
            "test_files": []
        }

        # Extract different types of keywords
        flags = [kw for kw in rfe_keywords if kw.startswith("--")]
        crds = [kw for kw in rfe_keywords if kw and kw[0].isupper() and kw.replace("-", "").replace("_", "").isalnum()]

        # Search for flag definitions
        for flag in flags[:5]:  # Limit to 5 flags
            flag_clean = flag.lstrip("-")
            # Search for flag definition patterns in Go code
            flag_results = self._search_code_for_pattern(
                repo_name,
                f'"{flag_clean}"',
                file_extensions=["go"],
                max_results=5
            )
            if flag_results:
                results["flag_definitions"].extend([
                    {
                        "flag": flag,
                        "file": r["path"],
                        "url": r.get("url", f"https://github.com/{repo_name}/blob/main/{r['path']}")
                    }
                    for r in flag_results
                ])

        # Search for CRD definitions
        for crd in crds[:5]:  # Limit to 5 CRDs
            # Search in CRD directories
            crd_results = self._search_code_for_pattern(
                repo_name,
                crd,
                paths=["config/crd", "api", "pkg/apis"],
                max_results=3
            )
            if crd_results:
                results["crd_definitions"].extend([
                    {
                        "crd": crd,
                        "file": r["path"],
                        "url": r.get("url", f"https://github.com/{repo_name}/blob/main/{r['path']}")
                    }
                    for r in crd_results
                ])

        # Search for config-related files based on general keywords
        config_keywords = [kw for kw in rfe_keywords if len(kw) > 3 and not kw.startswith("--")][:3]
        for keyword in config_keywords:
            config_results = self._search_code_for_pattern(
                repo_name,
                keyword,
                paths=["config", "pkg/config"],
                file_extensions=["go", "yaml", "yml"],
                max_results=3
            )
            if config_results:
                results["config_files"].extend([
                    {
                        "keyword": keyword,
                        "file": r["path"],
                        "url": r.get("url", f"https://github.com/{repo_name}/blob/main/{r['path']}")
                    }
                    for r in config_results
                ])

        # Search for controller files
        controller_keywords = [kw for kw in rfe_keywords if len(kw) > 3][:3]
        for keyword in controller_keywords:
            controller_results = self._search_code_for_pattern(
                repo_name,
                keyword,
                paths=["pkg/controller", "controllers"],
                file_extensions=["go"],
                max_results=3
            )
            if controller_results:
                results["controller_files"].extend([
                    {
                        "keyword": keyword,
                        "file": r["path"],
                        "url": r.get("url", f"https://github.com/{repo_name}/blob/main/{r['path']}")
                    }
                    for r in controller_results
                ])

        # Search for test files
        test_keywords = [kw for kw in rfe_keywords if len(kw) > 3][:3]
        for keyword in test_keywords:
            test_results = self._search_code_for_pattern(
                repo_name,
                keyword,
                paths=["test", "pkg"],
                file_extensions=["go"],
                filename_contains="_test.go",
                max_results=3
            )
            if test_results:
                results["test_files"].extend([
                    {
                        "keyword": keyword,
                        "file": r["path"],
                        "url": r.get("url", f"https://github.com/{repo_name}/blob/main/{r['path']}")
                    }
                    for r in test_results
                ])

        # Deduplicate results in each category
        for category in results:
            seen_files = set()
            unique_results = []
            for item in results[category]:
                file_path = item.get("file")
                if file_path and file_path not in seen_files:
                    seen_files.add(file_path)
                    unique_results.append(item)
            results[category] = unique_results

        return results

    def _search_code_for_pattern(
        self,
        repo_name: str,
        pattern: str,
        paths: Optional[List[str]] = None,
        file_extensions: Optional[List[str]] = None,
        filename_contains: Optional[str] = None,
        max_results: int = 5
    ) -> List[Dict]:
        """
        Search code for a pattern using gh search code

        Args:
            repo_name: Repository name
            pattern: Search pattern
            paths: Optional list of paths to search in
            file_extensions: Optional list of file extensions to filter
            filename_contains: Optional filename pattern
            max_results: Maximum results to return

        Returns:
            List of matching files with paths
        """
        # Build search query
        query_parts = [pattern]

        # Add repo restriction
        query_parts.append(f"repo:{repo_name}")

        # Add path restrictions
        if paths:
            path_query = " OR ".join([f"path:{p}" for p in paths])
            query_parts.append(f"({path_query})")

        # Add extension filter
        if file_extensions:
            ext_query = " OR ".join([f"extension:{ext}" for ext in file_extensions])
            query_parts.append(f"({ext_query})")

        # Add filename filter
        if filename_contains:
            query_parts.append(f"filename:{filename_contains}")

        query = " ".join(query_parts)

        # Execute search
        search_data = self._run_gh_command(
            ["search", "code", query, "--limit", str(max_results), "--json", "path,url"],
            cache_key=f"code_search_{repo_name.replace('/', '_')}_{hash(query) % 100000}"
        )

        if not search_data:
            return []

        try:
            results = json.loads(search_data)
            return results if isinstance(results, list) else []
        except json.JSONDecodeError:
            return []

    def analyze_dependencies(self, repo_name: str, rfe_keywords: List[str]) -> Dict:
        """
        Analyze go.mod or package.json for dependencies relevant to RFE

        Args:
            repo_name: Repository name
            rfe_keywords: Keywords from RFE to identify relevant dependencies

        Returns:
            Dict with dependencies and identified risks
        """
        result = {
            "dependencies": [],
            "risks": [],
            "recommendations": []
        }

        # Try to fetch go.mod
        gomod = self._run_gh_command(
            ["api", f"repos/{repo_name}/contents/go.mod", "--jq", ".content"],
            cache_key=f"gomod_deps_{repo_name.replace('/', '_')}"
        )

        if gomod:
            result = self._analyze_go_dependencies(gomod, rfe_keywords, repo_name)
        else:
            # Try package.json for Node.js projects
            packagejson = self._run_gh_command(
                ["api", f"repos/{repo_name}/contents/package.json", "--jq", ".content"],
                cache_key=f"packagejson_deps_{repo_name.replace('/', '_')}"
            )

            if packagejson:
                result = self._analyze_node_dependencies(packagejson, rfe_keywords, repo_name)

        return result

    def _analyze_go_dependencies(self, gomod_base64: str, rfe_keywords: List[str], repo_name: str) -> Dict:
        """Analyze Go dependencies from go.mod"""
        import base64
        import re

        result = {
            "dependencies": [],
            "risks": [],
            "recommendations": []
        }

        try:
            # Decode base64 content
            content = base64.b64decode(gomod_base64.strip()).decode('utf-8')
        except Exception as e:
            print(f"Warning: Failed to decode go.mod: {e}", file=sys.stderr)
            return result

        # Parse dependencies
        deps = {}
        for line in content.split('\n'):
            line = line.strip()
            # Match: github.com/org/repo v1.2.3
            match = re.match(r'^\s*(github\.com/[^\s]+|k8s\.io/[^\s]+|go\.opentelemetry\.io/[^\s]+)\s+v?([^\s]+)', line)
            if match:
                dep_path, version = match.groups()
                deps[dep_path] = version

        # Store all dependencies
        result["dependencies"] = [{"path": k, "version": v} for k, v in deps.items()]

        # Identify risks based on RFE keywords
        keywords_lower = [kw.lower() for kw in rfe_keywords]

        # Check for AWS dependencies
        if any("aws" in kw for kw in keywords_lower):
            aws_deps = {k: v for k, v in deps.items() if "aws" in k.lower()}
            if aws_deps:
                result["risks"].append({
                    "type": "AWS SDK Dependency",
                    "severity": "medium",
                    "dependencies": list(aws_deps.keys()),
                    "description": f"Uses AWS SDK: {', '.join(aws_deps.keys())}",
                    "mitigation": "Ensure FIPS-compliant AWS SDK version for GA. Verify AWS SDK supports required features."
                })

        # Check for Azure dependencies
        if any("azure" in kw for kw in keywords_lower):
            azure_deps = {k: v for k, v in deps.items() if "azure" in k.lower()}
            if azure_deps:
                result["risks"].append({
                    "type": "Azure SDK Dependency",
                    "severity": "medium",
                    "dependencies": list(azure_deps.keys()),
                    "description": f"Uses Azure SDK: {', '.join(azure_deps.keys())}",
                    "mitigation": "Verify Azure SDK version compatibility with OpenShift supported Azure regions"
                })

        # Check for GCP dependencies
        if any("gcp" in kw or "google" in kw for kw in keywords_lower):
            gcp_deps = {k: v for k, v in deps.items() if "google" in k.lower() and "cloud" in k.lower()}
            if gcp_deps:
                result["risks"].append({
                    "type": "GCP SDK Dependency",
                    "severity": "medium",
                    "dependencies": list(gcp_deps.keys()),
                    "description": f"Uses GCP SDK: {', '.join(gcp_deps.keys())}",
                    "mitigation": "Verify GCP SDK version compatibility and authentication methods"
                })

        # Check for Kubernetes version dependencies
        k8s_deps = {k: v for k, v in deps.items() if "k8s.io" in k}
        if k8s_deps:
            # Check for version mismatches or outdated versions
            for dep_path, version in k8s_deps.items():
                # Extract version number (e.g., "v0.28.0" -> "0.28")
                version_match = re.match(r'v?(\d+)\.(\d+)', version)
                if version_match:
                    major, minor = version_match.groups()
                    k8s_version = f"{major}.{minor}"

                    result["recommendations"].append({
                        "type": "Kubernetes Version",
                        "dependency": dep_path,
                        "current_version": version,
                        "recommendation": f"Ensure k8s.io dependencies match OpenShift supported Kubernetes version"
                    })

        # Check for security-related dependencies if RFE mentions security
        if any(kw in ["security", "auth", "certificate", "tls", "encrypt"] for kw in keywords_lower):
            crypto_deps = {k: v for k, v in deps.items() if any(term in k.lower() for term in ["crypto", "tls", "cert", "auth", "oauth"])}
            if crypto_deps:
                result["risks"].append({
                    "type": "Cryptography/Security Dependencies",
                    "severity": "high",
                    "dependencies": list(crypto_deps.keys()),
                    "description": "Security-sensitive dependencies detected",
                    "mitigation": "Ensure FIPS compliance, verify TLS versions (1.2+), review for known CVEs"
                })

        # Check for database dependencies
        db_keywords = ["database", "sql", "postgres", "mysql", "redis", "etcd"]
        if any(kw in keywords_lower for kw in db_keywords):
            db_deps = {k: v for k, v in deps.items() if any(db in k.lower() for db in ["sql", "postgres", "mysql", "redis", "etcd", "mongo"])}
            if db_deps:
                result["recommendations"].append({
                    "type": "Database Dependencies",
                    "dependencies": list(db_deps.keys()),
                    "recommendation": "Verify database client version compatibility and connection pooling settings"
                })

        return result

    def _analyze_node_dependencies(self, packagejson_base64: str, rfe_keywords: List[str], repo_name: str) -> Dict:
        """Analyze Node.js dependencies from package.json"""
        import base64

        result = {
            "dependencies": [],
            "risks": [],
            "recommendations": []
        }

        try:
            # Decode base64 content
            content = base64.b64decode(packagejson_base64.strip()).decode('utf-8')
            package_data = json.loads(content)
        except Exception as e:
            print(f"Warning: Failed to parse package.json: {e}", file=sys.stderr)
            return result

        # Extract dependencies
        deps = package_data.get("dependencies", {})
        dev_deps = package_data.get("devDependencies", {})

        # Store all dependencies
        all_deps = {**deps, **dev_deps}
        result["dependencies"] = [{"name": k, "version": v} for k, v in all_deps.items()]

        # Similar risk analysis for Node.js dependencies
        keywords_lower = [kw.lower() for kw in rfe_keywords]

        # Check for AWS SDK
        if any("aws" in kw for kw in keywords_lower):
            aws_deps = {k: v for k, v in all_deps.items() if "aws-sdk" in k.lower() or "@aws-sdk" in k.lower()}
            if aws_deps:
                result["risks"].append({
                    "type": "AWS SDK Dependency",
                    "severity": "medium",
                    "dependencies": list(aws_deps.keys()),
                    "description": f"Uses AWS SDK for JavaScript/Node.js",
                    "mitigation": "Verify AWS SDK version and feature compatibility"
                })

        return result


def main():
    """Test the analyzer"""
    if len(sys.argv) < 2:
        print("Usage: github_repo_analyzer.py <component-name>")
        print("\nExample: github_repo_analyzer.py cert-manager")
        sys.exit(1)

    component_name = sys.argv[1]

    analyzer = GitHubRepoAnalyzer()

    print(f"Analyzing component: {component_name}\n")

    # Discover repositories
    repos = analyzer.discover_repositories(component_name)
    print("=" * 70)
    print("REPOSITORIES")
    print("=" * 70)
    print(json.dumps(repos, indent=2))

    # Analyze structure if downstream repo found
    if repos["downstream"]:
        downstream_name = repos["downstream"]["name"]
        print(f"\n{'=' * 70}")
        print(f"CODEBASE STRUCTURE: {downstream_name}")
        print("=" * 70)
        structure = analyzer.analyze_codebase_structure(downstream_name)
        print(json.dumps(structure, indent=2))


if __name__ == "__main__":
    main()
