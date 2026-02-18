#!/usr/bin/env python3
"""
Comprehensive Component Context Gatherer
Main orchestrator for analyzing OpenShift components and generating comprehensive context
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict, Optional

# Import our analyzers
from github_repo_analyzer import GitHubRepoAnalyzer
from github_pr_analyzer import GitHubPRAnalyzer
from context_synthesizer import ContextSynthesizer
from operand_discovery import OperandDiscovery


class ComponentContextGatherer:
    """Orchestrates comprehensive component context gathering"""

    def __init__(self, cache_dir: Optional[str] = None, verbose: bool = False):
        """
        Initialize the gatherer

        Args:
            cache_dir: Directory for caching GitHub API results
            verbose: Enable verbose output
        """
        self.cache_dir = cache_dir or ".work/jira/analyze-rfe/cache"
        self.verbose = verbose

        # Initialize analyzers
        self.repo_analyzer = GitHubRepoAnalyzer(cache_dir=self.cache_dir)
        self.pr_analyzer = GitHubPRAnalyzer(cache_dir=self.cache_dir)
        self.synthesizer = ContextSynthesizer()
        self.operand_discovery = OperandDiscovery(cache_dir=self.cache_dir)

    def gather_context(
        self,
        component_name: str,
        rfe_keywords: Optional[List[str]] = None,
        max_prs: int = 50,
        deep_dive_prs: int = 3,
        analyze_upstream: Optional[bool] = None,
        analyze_operands: Optional[bool] = None,
        interactive: bool = True
    ) -> Dict:
        """
        Gather comprehensive context for a component

        Args:
            component_name: Component name (e.g., "cert-manager", "hypershift")
            rfe_keywords: Keywords from RFE for PR search
            max_prs: Maximum PRs to search
            deep_dive_prs: Number of PRs to analyze in detail
            analyze_upstream: Whether to analyze upstream repo (None = ask user if interactive)
            analyze_operands: Whether to analyze operand repos (None = ask user if interactive)
            interactive: Whether to prompt user for upstream/operand analysis

        Returns:
            Dict with all gathered context
        """
        context = {
            "component": component_name,
            "repositories": {},
            "structure": {},
            "pr_insights": [],
            "adrs": [],
            "lessons": [],
            "rfe_related_files": {},  # Phase 2
            "bug_patterns": [],        # Phase 2
            "dependencies": {},        # Phase 2
            "markdown": ""
        }

        self._log(f"Analyzing component: {component_name}")

        # Step 1: Discover repositories
        self._log("Step 1: Discovering repositories...")
        repos = self.repo_analyzer.discover_repositories(component_name)
        context["repositories"] = repos

        if not repos.get("downstream"):
            self._log(f"Warning: No downstream repository found for {component_name}")
            context["markdown"] = self._generate_no_repo_message(component_name)
            return context

        downstream_repo = repos["downstream"]["name"]
        self._log(f"Found downstream repo: {downstream_repo}")

        # Step 2: Analyze codebase structure
        self._log("Step 2: Analyzing codebase structure...")
        structure = self.repo_analyzer.analyze_codebase_structure(downstream_repo)
        context["structure"] = structure
        self._log(f"Architecture: {structure.get('architecture', 'Unknown')}")

        # Step 2.5: Discover and analyze operands (if this is an operator)
        is_operator = self.operand_discovery.is_operator(downstream_repo, structure)
        context["is_operator"] = is_operator

        if is_operator:
            try:
                self._log("Step 2.5: Discovered this is an Operator, checking for operands...")
                operands = self.operand_discovery.discover_operands(downstream_repo)

                if operands:
                    self._log(f"Found {len(operands)} potential operand(s)")

                    # Enrich with repository info
                    operands_enriched = self.operand_discovery.enrich_with_repositories(operands)

                    # Filter to only those with repositories
                    operands_with_repos = [o for o in operands_enriched if o.get("repository")]

                    if operands_with_repos:
                        self._log(f"Found {len(operands_with_repos)} operand(s) with repositories")

                        # Decide whether to analyze operands
                        should_analyze_operands = analyze_operands

                        if should_analyze_operands is None and interactive:
                            should_analyze_operands = self._ask_user_for_operand_analysis(
                                component_name,
                                operands_with_repos
                            )

                        if should_analyze_operands:
                            context["operands"] = []

                            for operand in operands_with_repos:
                                operand_name = operand.get("name")
                                operand_repo = operand["repository"]["name"]

                                self._log(f"  Analyzing operand: {operand_name} ({operand_repo})")

                                try:
                                    # Analyze operand repository (subset of full analysis)
                                    operand_context = self._analyze_operand(
                                        operand_name,
                                        operand_repo,
                                        rfe_keywords,
                                        max_prs=5,  # Fewer PRs for operands
                                        deep_dive_prs=2
                                    )

                                    context["operands"].append({
                                        "name": operand_name,
                                        "source": operand.get("source"),
                                        "repository": operand["repository"],
                                        "context": operand_context
                                    })
                                except Exception as e:
                                    self._log(f"  Warning: Failed to analyze operand {operand_name}: {e}")

                            self._log(f"  Analyzed {len(context['operands'])} operand(s)")
                        else:
                            self._log("  Skipping operand analysis (user declined or not requested)")
                    else:
                        self._log("  No operands with discoverable repositories")
                else:
                    self._log("  No operands discovered")
            except Exception as e:
                self._log(f"Warning: Operand discovery failed: {e}")

        # Step 3: Search and analyze PRs (if keywords provided)
        if rfe_keywords:
            try:
                self._log(f"Step 3: Searching PRs with keywords: {rfe_keywords}")
                prs = self.pr_analyzer.search_relevant_prs(
                    downstream_repo,
                    rfe_keywords,
                    max_results=max_prs
                )
                self._log(f"Found {len(prs)} relevant PRs")

                # Analyze top PRs in detail
                for i, pr in enumerate(prs[:deep_dive_prs]):
                    try:
                        self._log(f"  Analyzing PR #{pr['number']}: {pr['title']}")
                        pr_details = self.pr_analyzer.analyze_pr_details(downstream_repo, pr['number'])

                        if pr_details:
                            insights = self.pr_analyzer.extract_design_insights(pr_details)
                            effort = self.pr_analyzer.analyze_pr_effort(pr_details)

                            context["pr_insights"].append({
                                "pr": pr,
                                "details": pr_details,
                                "insights": insights,
                                "effort": effort
                            })
                    except Exception as e:
                        self._log(f"  Warning: Failed to analyze PR #{pr['number']}: {e}")
            except Exception as e:
                self._log(f"Warning: PR search failed: {e}")
        else:
            self._log("Step 3: Skipping PR analysis (no keywords provided)")

        # Step 4: Search for ADRs
        try:
            self._log("Step 4: Searching for Architecture Decision Records...")
            adrs = self.pr_analyzer.search_adrs(downstream_repo)
            context["adrs"] = adrs
            if adrs:
                self._log(f"Found {len(adrs)} ADRs")
        except Exception as e:
            self._log(f"Warning: ADR search failed: {e}")
            context["adrs"] = []

        # Step 5: Search for lessons learned
        try:
            self._log("Step 5: Searching for lessons learned...")
            lessons = self.pr_analyzer.search_lessons_learned_issues(downstream_repo)
            context["lessons"] = lessons
            if lessons:
                self._log(f"Found {len(lessons)} issues with lessons")
        except Exception as e:
            self._log(f"Warning: Lessons search failed: {e}")
            context["lessons"] = []

        # Step 5.1: Find RFE-specific code files (Phase 2)
        if rfe_keywords:
            try:
                self._log("Step 5.1: Finding RFE-specific code files...")
                rfe_files = self.repo_analyzer.find_rfe_related_files(downstream_repo, rfe_keywords)
                context["rfe_related_files"] = rfe_files

                total_files = sum(len(v) for v in rfe_files.values())
                if total_files > 0:
                    self._log(f"Found {total_files} RFE-related files")
            except Exception as e:
                self._log(f"Warning: RFE file search failed: {e}")
                context["rfe_related_files"] = {}
        else:
            self._log("Step 5.1: Skipping RFE file search (no keywords provided)")

        # Step 5.2: Search for related bug patterns (Phase 2)
        if rfe_keywords:
            try:
                self._log("Step 5.2: Searching for related bug patterns...")
                bug_patterns = self.pr_analyzer.search_related_bugs(component_name, rfe_keywords)
                context["bug_patterns"] = bug_patterns
                if bug_patterns:
                    self._log(f"Found {len(bug_patterns)} bugs with lessons")
            except Exception as e:
                self._log(f"Warning: Bug pattern search failed: {e}")
                context["bug_patterns"] = []
        else:
            self._log("Step 5.2: Skipping bug pattern search (no keywords provided)")

        # Step 5.3: Analyze dependencies (Phase 2)
        try:
            self._log("Step 5.3: Analyzing dependencies...")
            dependencies = self.repo_analyzer.analyze_dependencies(downstream_repo, rfe_keywords or [])
            context["dependencies"] = dependencies

            dep_count = len(dependencies.get("dependencies", []))
            risk_count = len(dependencies.get("risks", []))
            if dep_count > 0:
                self._log(f"Analyzed {dep_count} dependencies, found {risk_count} risks")
        except Exception as e:
            self._log(f"Warning: Dependency analysis failed: {e}")
            context["dependencies"] = {}

        # Step 5.5: Analyze upstream repository (if requested)
        upstream_repo = repos.get("upstream")
        if upstream_repo and isinstance(upstream_repo, dict) and upstream_repo.get("name"):
            upstream_name = upstream_repo["name"]

            # Decide whether to analyze upstream
            should_analyze_upstream = analyze_upstream

            if should_analyze_upstream is None and interactive:
                # Ask user
                should_analyze_upstream = self._ask_user_for_upstream_analysis(
                    component_name,
                    upstream_name
                )

            if should_analyze_upstream:
                try:
                    self._log(f"Step 5.5: Analyzing upstream repository: {upstream_name}...")

                    # Analyze upstream structure
                    self._log("  Analyzing upstream codebase structure...")
                    upstream_structure = self.repo_analyzer.analyze_codebase_structure(upstream_name)
                    context["upstream_structure"] = upstream_structure
                    self._log(f"  Upstream architecture: {upstream_structure.get('architecture', 'Unknown')}")

                    # Search upstream PRs (if keywords provided)
                    if rfe_keywords:
                        self._log(f"  Searching upstream PRs with keywords: {rfe_keywords}")
                        upstream_prs = self.pr_analyzer.search_relevant_prs(
                            upstream_name,
                            rfe_keywords,
                            max_results=max_prs
                        )
                        self._log(f"  Found {len(upstream_prs)} relevant upstream PRs")

                        # Analyze top upstream PRs
                        upstream_insights = []
                        for i, pr in enumerate(upstream_prs[:deep_dive_prs]):
                            self._log(f"    Analyzing upstream PR #{pr['number']}: {pr['title']}")
                            pr_details = self.pr_analyzer.analyze_pr_details(upstream_name, pr['number'])

                            if pr_details:
                                insights = self.pr_analyzer.extract_design_insights(pr_details)
                                effort = self.pr_analyzer.analyze_pr_effort(pr_details)

                                upstream_insights.append({
                                    "pr": pr,
                                    "details": pr_details,
                                    "insights": insights,
                                    "effort": effort
                                })

                        context["upstream_pr_insights"] = upstream_insights

                    # Search upstream ADRs
                    self._log("  Searching upstream ADRs...")
                    upstream_adrs = self.pr_analyzer.search_adrs(upstream_name)
                    context["upstream_adrs"] = upstream_adrs
                    if upstream_adrs:
                        self._log(f"  Found {len(upstream_adrs)} upstream ADRs")

                    self._log("  Upstream analysis complete!")
                except Exception as e:
                    self._log(f"Warning: Upstream analysis failed: {e}")
                    # Graceful degradation - continue without upstream context
                    context["upstream_structure"] = None
            else:
                self._log("Step 5.5: Skipping upstream analysis (user declined or not requested)")
        else:
            self._log("No upstream repository found or invalid upstream data")

        # Step 6: Synthesize comprehensive context
        self._log("Step 6: Synthesizing comprehensive context...")
        markdown = self.synthesizer.synthesize_component_context(
            component_name,
            context["repositories"],
            context["structure"],
            context["pr_insights"],
            context["adrs"],
            context["lessons"],
            upstream_structure=context.get("upstream_structure"),
            upstream_pr_insights=context.get("upstream_pr_insights"),
            upstream_adrs=context.get("upstream_adrs"),
            is_operator=context.get("is_operator", False),
            operands=context.get("operands", []),
            rfe_related_files=context.get("rfe_related_files"),  # Phase 2
            bug_patterns=context.get("bug_patterns"),            # Phase 2
            dependencies=context.get("dependencies")             # Phase 2
        )
        context["markdown"] = markdown

        self._log("Context gathering complete!")

        return context

    def gather_multiple_components(
        self,
        component_names: List[str],
        rfe_keywords: Optional[List[str]] = None,
        max_prs: int = 50,
        deep_dive_prs: int = 3,
        analyze_upstream: Optional[bool] = None,
        analyze_operands: Optional[bool] = None,
        interactive: bool = True
    ) -> Dict[str, Dict]:
        """
        Gather context for multiple components

        Args:
            component_names: List of component names
            rfe_keywords: Keywords from RFE
            max_prs: Max PRs per component
            deep_dive_prs: PRs to analyze in detail per component
            analyze_upstream: Whether to analyze upstream repos (None = ask user)
            analyze_operands: Whether to analyze operand repos (None = ask user)
            interactive: Whether to prompt user for upstream/operand analysis

        Returns:
            Dict mapping component name to context
        """
        results = {}

        for component in component_names:
            self._log(f"\n{'=' * 70}")
            self._log(f"Component: {component}")
            self._log('=' * 70)

            context = self.gather_context(
                component,
                rfe_keywords=rfe_keywords,
                max_prs=max_prs,
                deep_dive_prs=deep_dive_prs,
                analyze_upstream=analyze_upstream,
                analyze_operands=analyze_operands,
                interactive=interactive
            )
            results[component] = context

        return results

    def _ask_user_for_operand_analysis(self, component_name: str, operands: List[Dict]) -> bool:
        """
        Ask user if operand analysis should be performed

        Args:
            component_name: Operator component name
            operands: List of discovered operands with repositories

        Returns:
            True if user wants operand analysis
        """
        print(f"\n{'=' * 70}", file=sys.stderr)
        print(f"Operands Found for {component_name}", file=sys.stderr)
        print('=' * 70, file=sys.stderr)
        print(f"This is an Operator managing {len(operands)} operand(s):", file=sys.stderr)

        for i, operand in enumerate(operands, 1):
            operand_name = operand.get("name")
            operand_repo = operand.get("repository", {}).get("name", "Unknown")
            print(f"  {i}. {operand_name} ({operand_repo})", file=sys.stderr)

        print(f"\nOperand analysis includes:", file=sys.stderr)
        print(f"  - Codebase structure for each operand", file=sys.stderr)
        print(f"  - Historical PR analysis", file=sys.stderr)
        print(f"  - Implementation patterns", file=sys.stderr)
        print(f"\nThis is useful for:", file=sys.stderr)
        print(f"  - Understanding operator vs operand responsibilities", file=sys.stderr)
        print(f"  - Determining where to implement RFE (operator or operand)", file=sys.stderr)
        print(f"  - Comprehensive view of the full component stack", file=sys.stderr)
        print(f"\nNote: This will add ~10-20 seconds per operand", file=sys.stderr)
        print('=' * 70, file=sys.stderr)

        while True:
            response = input(f"\nAnalyze operand repositories? [y/N]: ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no', '']:
                return False
            else:
                print("Please enter 'y' or 'n'", file=sys.stderr)

    def _analyze_operand(
        self,
        operand_name: str,
        operand_repo: str,
        rfe_keywords: Optional[List[str]] = None,
        max_prs: int = 5,
        deep_dive_prs: int = 2
    ) -> Dict:
        """
        Analyze an operand repository (simplified version of full analysis)

        Args:
            operand_name: Operand name
            operand_repo: Operand repository name
            rfe_keywords: Keywords for PR search
            max_prs: Max PRs to search
            deep_dive_prs: PRs to analyze in detail

        Returns:
            Dict with operand analysis
        """
        operand_context = {}

        # Analyze structure
        structure = self.repo_analyzer.analyze_codebase_structure(operand_repo)
        operand_context["structure"] = structure

        # Search PRs if keywords provided
        if rfe_keywords:
            prs = self.pr_analyzer.search_relevant_prs(
                operand_repo,
                rfe_keywords,
                max_results=max_prs
            )

            # Analyze top PRs
            pr_insights = []
            for pr in prs[:deep_dive_prs]:
                pr_details = self.pr_analyzer.analyze_pr_details(operand_repo, pr['number'])
                if pr_details:
                    insights = self.pr_analyzer.extract_design_insights(pr_details)
                    effort = self.pr_analyzer.analyze_pr_effort(pr_details)
                    pr_insights.append({
                        "pr": pr,
                        "details": pr_details,
                        "insights": insights,
                        "effort": effort
                    })

            operand_context["pr_insights"] = pr_insights

        # Search ADRs
        adrs = self.pr_analyzer.search_adrs(operand_repo)
        operand_context["adrs"] = adrs

        return operand_context

    def _ask_user_for_upstream_analysis(self, component_name: str, upstream_name: str) -> bool:
        """
        Ask user if upstream analysis should be performed

        Args:
            component_name: Component being analyzed
            upstream_name: Upstream repository name

        Returns:
            True if user wants upstream analysis
        """
        print(f"\n{'=' * 70}", file=sys.stderr)
        print(f"Upstream Repository Found for {component_name}", file=sys.stderr)
        print('=' * 70, file=sys.stderr)
        print(f"Upstream: {upstream_name}", file=sys.stderr)
        print(f"\nUpstream analysis includes:", file=sys.stderr)
        print(f"  - Codebase structure and architecture", file=sys.stderr)
        print(f"  - Historical PR analysis and design decisions", file=sys.stderr)
        print(f"  - Architecture Decision Records (ADRs)", file=sys.stderr)
        print(f"\nThis is useful for:", file=sys.stderr)
        print(f"  - Understanding original design intent", file=sys.stderr)
        print(f"  - Finding upstream features to adopt", file=sys.stderr)
        print(f"  - Identifying differences between upstream/downstream", file=sys.stderr)
        print(f"\nNote: This will add ~15-30 seconds to analysis time", file=sys.stderr)
        print('=' * 70, file=sys.stderr)

        while True:
            response = input(f"\nAnalyze upstream repository '{upstream_name}'? [y/N]: ").strip().lower()
            if response in ['y', 'yes']:
                return True
            elif response in ['n', 'no', '']:
                return False
            else:
                print("Please enter 'y' or 'n'", file=sys.stderr)

    def _generate_no_repo_message(self, component_name: str) -> str:
        """Generate message when no repository found"""
        return f"""### Component: {component_name}

**No public repository found for analysis**

The component `{component_name}` does not have a discoverable public repository in the OpenShift GitHub organization. This may indicate:
- Private repository requiring additional access
- Component is part of a larger repository
- Non-standard repository naming

**Recommendation**: Manual investigation required to identify the correct repository.
"""

    def _log(self, message: str):
        """Log message if verbose mode enabled"""
        if self.verbose:
            print(message, file=sys.stderr)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Gather comprehensive component context for RFE analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze single component
  gather_component_context.py cert-manager

  # Analyze with RFE keywords for PR search
  gather_component_context.py cert-manager --keywords "certificate rotation" "ACME"

  # Analyze multiple components
  gather_component_context.py hypershift cert-manager --keywords "certificate" --verbose

  # Customize PR analysis depth
  gather_component_context.py cert-manager --keywords "cert" --max-prs 20 --deep-dive 5

  # Output to file
  gather_component_context.py cert-manager -o output.md

  # Output JSON for programmatic use
  gather_component_context.py cert-manager --json -o output.json
        """
    )

    parser.add_argument(
        "components",
        nargs="+",
        help="Component name(s) to analyze (e.g., cert-manager, hypershift)"
    )

    parser.add_argument(
        "-k", "--keywords",
        nargs="*",
        help="Keywords from RFE for PR search (e.g., 'certificate rotation')"
    )

    parser.add_argument(
        "--max-prs",
        type=int,
        default=50,
        help="Maximum PRs to search per component (default: 50)"
    )

    parser.add_argument(
        "--deep-dive",
        type=int,
        default=3,
        help="Number of PRs to analyze in detail (default: 3)"
    )

    parser.add_argument(
        "--cache-dir",
        help="Directory for caching GitHub API results (default: .work/jira/analyze-rfe/cache)"
    )

    parser.add_argument(
        "-o", "--output",
        help="Output file (default: stdout)"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of markdown"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output"
    )

    parser.add_argument(
        "--analyze-upstream",
        action="store_true",
        help="Always analyze upstream repositories (default behavior)"
    )

    parser.add_argument(
        "--skip-upstream",
        action="store_true",
        help="Skip analyzing upstream repositories"
    )

    parser.add_argument(
        "--analyze-operands",
        action="store_true",
        help="Always analyze operand repositories (default behavior)"
    )

    parser.add_argument(
        "--skip-operands",
        action="store_true",
        help="Skip analyzing operand repositories"
    )

    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Non-interactive mode (analyzes upstream and operands by default)"
    )

    args = parser.parse_args()

    # Determine upstream analysis setting
    if args.skip_upstream:
        analyze_upstream = False
    elif args.analyze_upstream:
        analyze_upstream = True
    else:
        analyze_upstream = True  # Default: analyze upstream

    # Determine operand analysis setting
    if args.skip_operands:
        analyze_operands = False
    elif args.analyze_operands:
        analyze_operands = True
    else:
        analyze_operands = True  # Default: analyze operands

    # Determine interactive mode
    interactive = not args.no_interactive

    # Initialize gatherer
    gatherer = ComponentContextGatherer(
        cache_dir=args.cache_dir,
        verbose=args.verbose
    )

    # Gather context
    if len(args.components) == 1:
        # Single component
        context = gatherer.gather_context(
            args.components[0],
            rfe_keywords=args.keywords,
            max_prs=args.max_prs,
            deep_dive_prs=args.deep_dive,
            analyze_upstream=analyze_upstream,
            analyze_operands=analyze_operands,
            interactive=interactive
        )

        # Output
        if args.json:
            output = json.dumps(context, indent=2)
        else:
            output = context["markdown"]

    else:
        # Multiple components
        contexts = gatherer.gather_multiple_components(
            args.components,
            rfe_keywords=args.keywords,
            max_prs=args.max_prs,
            deep_dive_prs=args.deep_dive,
            analyze_upstream=analyze_upstream,
            analyze_operands=analyze_operands,
            interactive=interactive
        )

        # Output
        if args.json:
            output = json.dumps(contexts, indent=2)
        else:
            # Combine markdown
            markdown_parts = []
            for component, context in contexts.items():
                markdown_parts.append(context["markdown"])
            output = "\n\n---\n\n".join(markdown_parts)

    # Write output
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output)
        if args.verbose:
            print(f"\nOutput written to: {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
