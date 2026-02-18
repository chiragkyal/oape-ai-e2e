#!/usr/bin/env python3
"""
Component Context Synthesizer
Combines repository and PR analysis into comprehensive component context
"""

import json
from typing import Dict, List
from datetime import datetime


class ContextSynthesizer:
    """Synthesizes component context from various sources"""

    def synthesize_component_context(
        self,
        component_name: str,
        repo_data: Dict,
        structure_data: Dict,
        pr_insights: List[Dict],
        adrs: List[Dict],
        lessons: List[Dict],
        upstream_structure: Dict = None,
        upstream_pr_insights: List[Dict] = None,
        upstream_adrs: List[Dict] = None,
        is_operator: bool = False,
        operands: List[Dict] = None,
        rfe_related_files: Dict = None,
        bug_patterns: List[Dict] = None,
        dependencies: Dict = None
    ) -> str:
        """
        Generate comprehensive component context in markdown

        Args:
            component_name: Component name
            repo_data: Repository discovery results
            structure_data: Codebase structure analysis
            pr_insights: List of PR analysis results
            adrs: Architecture Decision Records
            lessons: Lessons learned from issues
            upstream_structure: Upstream codebase structure (optional)
            upstream_pr_insights: Upstream PR analysis (optional)
            upstream_adrs: Upstream ADRs (optional)
            is_operator: Whether this is an operator (optional)
            operands: List of operand analysis results (optional)
            rfe_related_files: RFE-specific code files (Phase 2)
            bug_patterns: Related bug patterns and lessons (Phase 2)
            dependencies: Dependency analysis results (Phase 2)

        Returns:
            Markdown formatted component context
        """
        sections = []

        # Header
        sections.append(f"### Component: {component_name}\n")

        # Repositories
        sections.append(self._format_repositories(repo_data))

        # What/Why/How
        sections.append(self._format_component_overview(repo_data, structure_data, is_operator))

        # Operands (if operator with operands)
        if is_operator and operands:
            sections.append(self._format_operands(operands))

        # RFE-Specific Code Files (Phase 2)
        if rfe_related_files and any(rfe_related_files.values()):
            sections.append(self._format_rfe_related_files(rfe_related_files))

        # Dependencies (Phase 2)
        if dependencies and (dependencies.get("dependencies") or dependencies.get("risks")):
            sections.append(self._format_dependencies(dependencies))

        # Key Implementation Patterns
        if pr_insights:
            sections.append(self._format_implementation_patterns(pr_insights, structure_data))

        # Critical Code Paths
        if structure_data.get("key_packages"):
            sections.append(self._format_code_paths(structure_data))

        # Bug Patterns and Lessons (Phase 2)
        if bug_patterns:
            sections.append(self._format_bug_patterns(bug_patterns))

        # Historical Context
        if pr_insights or adrs or lessons:
            sections.append(self._format_historical_context(pr_insights, adrs, lessons))

        # Upstream Analysis (if provided)
        has_upstream = upstream_structure or upstream_pr_insights or upstream_adrs
        if has_upstream:
            sections.append(self._format_upstream_analysis(
                repo_data,
                upstream_structure,
                upstream_pr_insights,
                upstream_adrs,
                structure_data  # For comparison
            ))

        # Risk Factors
        sections.append(self._format_risk_factors(structure_data, pr_insights, lessons, dependencies))

        # Recommended Approach
        sections.append(self._format_recommended_approach(
            repo_data,
            structure_data,
            pr_insights,
            upstream_structure,
            upstream_pr_insights
        ))

        return "\n".join(sections)

    def _format_repositories(self, repo_data: Dict) -> str:
        """Format repository information"""
        lines = ["**Repositories**:"]

        downstream = repo_data.get("downstream")
        if downstream:
            lines.append(f"- Downstream: {downstream.get('name', 'Unknown')}")
        else:
            lines.append("- Downstream: Not found")

        upstream = repo_data.get("upstream")
        if upstream:
            lines.append(f"- Upstream: {upstream.get('name', 'Unknown')}")

        related = repo_data.get("related", [])
        if related:
            related_names = [r.get("name", "").replace("openshift/", "") for r in related[:3]]
            lines.append(f"- Related: {', '.join(related_names)}")

        return "\n".join(lines) + "\n"

    def _format_component_overview(self, repo_data: Dict, structure_data: Dict, is_operator: bool = False) -> str:
        """Format What/Why/How section"""
        lines = []

        # What it does
        downstream = repo_data.get("downstream", {})
        description = downstream.get("description", "")
        if description:
            what_it_does = description
        else:
            what_it_does = f"{structure_data.get('architecture', 'Component')} for OpenShift"

        if is_operator:
            what_it_does += " (Operator managing workload operands)"

        lines.append(f"**What it does**: {what_it_does}\n")

        # Why it exists
        lines.append("**Why it exists**: Provides critical functionality for OpenShift platform operations\n")

        # How it works
        lines.append("**How it works**:")
        arch = structure_data.get("architecture", "Unknown")
        lines.append(f"- Architecture: {arch}")

        # Key packages
        packages = structure_data.get("key_packages", [])
        if packages:
            top_packages = [f"{p.get('name', 'unknown')}" for p in packages[:3]]
            lines.append(f"- Key Packages: {', '.join(top_packages)}")

        # API Types for operators
        if arch == "Kubernetes Operator":
            crds = structure_data.get("api_types", [])
            if crds:
                crd_names = [c.get("file", "").replace(".yaml", "").split("_")[-1] for c in crds[:3]]
                lines.append(f"- API Types (CRDs): {', '.join(crd_names)}")

        # Integration points
        lines.append("- Integration: Kubernetes API, OpenShift control plane")

        return "\n".join(lines) + "\n"

    def _format_operands(self, operands: List[Dict]) -> str:
        """Format operand repositories analysis"""
        lines = ["**Operand Repositories**:\n"]

        lines.append("*This operator manages the following operands:*\n")

        for i, operand in enumerate(operands, 1):
            operand_name = operand.get("name", "Unknown")
            operand_repo = operand.get("repository", {}).get("name", "Unknown")
            operand_desc = operand.get("repository", {}).get("description", "")

            lines.append(f"{i}. **{operand_name}** (`{operand_repo}`)")

            if operand_desc:
                lines.append(f"   - {operand_desc}")

            # Add architecture if available
            operand_context = operand.get("context", {})
            operand_structure = operand_context.get("structure", {})
            operand_arch = operand_structure.get("architecture")

            if operand_arch:
                lines.append(f"   - Architecture: {operand_arch}")

            # Add key packages if available
            operand_packages = operand_structure.get("key_packages", [])
            if operand_packages:
                pkg_names = [p.get("name", "") for p in operand_packages[:2]]
                lines.append(f"   - Key packages: {', '.join(pkg_names)}")

            # Add note about PR insights if available
            operand_prs = operand_context.get("pr_insights", [])
            if operand_prs:
                lines.append(f"   - Analyzed {len(operand_prs)} relevant PR(s)")

            lines.append("")

        # Add guidance on operator vs operand responsibilities
        lines.append("**Operator vs Operand Responsibilities**:")
        lines.append("- **Operator**: Lifecycle management, configuration, upgrades, monitoring")
        lines.append("- **Operands**: Core workload functionality, business logic")
        lines.append("")

        lines.append("**Implementation Guidance**:")
        lines.append("- **Configuration/lifecycle changes**: Implement in operator")
        lines.append("- **Core functionality changes**: Implement in operand")
        lines.append("- **API/CRD changes**: May require both operator and operand changes")
        lines.append("")

        return "\n".join(lines)

    def _format_implementation_patterns(self, pr_insights: List[Dict], structure_data: Dict) -> str:
        """Format key implementation patterns"""
        lines = ["**Key Implementation Patterns**:"]

        # Extract patterns from PR insights
        patterns_found = []

        for insight in pr_insights[:3]:
            pr_details = insight.get("details", {})
            extracted = insight.get("insights", {})

            # From design sections
            for design in extracted.get("design_sections", [])[:2]:
                if design and len(design) > 50:
                    pattern_name = self._extract_pattern_name(design)
                    patterns_found.append({
                        "name": pattern_name,
                        "description": design[:200].replace('\n', ' ')
                    })

        # Add architecture-based patterns
        arch = structure_data.get("architecture")
        if arch == "Kubernetes Operator":
            patterns_found.insert(0, {
                "name": "Controller Reconciliation",
                "description": "Watches Kubernetes resources and reconciles desired state with actual state"
            })

        # Format patterns
        if patterns_found:
            for i, pattern in enumerate(patterns_found[:3], 1):
                lines.append(f"{i}. **{pattern['name']}**: {pattern['description']}")
        else:
            lines.append("1. **Standard patterns**: Follows OpenShift operator conventions")

        return "\n".join(lines) + "\n"

    def _format_code_paths(self, structure_data: Dict) -> str:
        """Format critical code paths"""
        lines = ["**Critical Code Paths**:"]

        controllers = structure_data.get("controllers", [])
        if controllers:
            for controller in controllers[:3]:
                lines.append(f"- `pkg/controllers/{controller}`: Core reconciliation logic")

        packages = structure_data.get("key_packages", [])
        if packages:
            for pkg in packages[:2]:
                pkg_name = pkg.get("name", "")
                lines.append(f"- `pkg/{pkg_name}/`: {self._infer_package_purpose(pkg_name)}")

        if not controllers and not packages:
            lines.append("- See repository structure for code organization")

        return "\n".join(lines) + "\n"

    def _format_historical_context(self, pr_insights: List[Dict], adrs: List[Dict], lessons: List[Dict]) -> str:
        """Format historical context section"""
        lines = ["**Historical Context**:\n"]

        # Relevant PRs
        if pr_insights:
            lines.append("**Relevant PRs**:")
            for insight in pr_insights[:3]:
                pr = insight.get("pr", {})
                pr_insights_data = insight.get("insights", {})

                pr_num = pr.get("number")
                pr_title = pr.get("title", "")
                merged_at = pr.get("mergedAt", "")

                # Parse date
                date_str = ""
                if merged_at:
                    try:
                        date_obj = datetime.fromisoformat(merged_at.replace('Z', '+00:00'))
                        date_str = date_obj.strftime("%Y-%m")
                    except (ValueError, TypeError):
                        pass

                lines.append(f"- PR #{pr_num} ({date_str}): {pr_title}")

                # Design insight
                design_sections = pr_insights_data.get("design_sections", [])
                if design_sections:
                    design_snippet = design_sections[0][:150].replace('\n', ' ')
                    lines.append(f"  - **Design**: {design_snippet}...")

                # Rationale
                rationale = pr_insights_data.get("rationale", [])
                if rationale:
                    rationale_snippet = rationale[0][:150].replace('\n', ' ')
                    lines.append(f"  - **Why**: {rationale_snippet}...")

                # Effort
                effort = insight.get("effort", {})
                if effort:
                    size = effort.get("size_category", "")
                    files = effort.get("changed_files", 0)
                    lines.append(f"  - **Scope**: {size} ({files} files changed)")

                lines.append("")

        # ADRs
        if adrs:
            lines.append("**Architecture Decisions**:")
            for adr in adrs[:2]:
                adr_name = adr.get("name", "").replace(".md", "")
                adr_url = adr.get("url", "")
                lines.append(f"- **{adr_name}**: See {adr_url}")
            lines.append("")

        # Lessons learned
        if lessons:
            lines.append("**Lessons Learned**:")
            for lesson in lessons[:2]:
                lesson_num = lesson.get("number")
                lesson_title = lesson.get("title", "")
                lines.append(f"- Issue #{lesson_num}: {lesson_title}")
                # Extract lesson from body
                body = lesson.get("body", "")
                if "lesson" in body.lower() or "learned" in body.lower():
                    snippet = self._extract_lesson_snippet(body)
                    if snippet:
                        lines.append(f"  - **Lesson**: {snippet}")
            lines.append("")

        return "\n".join(lines)

    def _format_risk_factors(self, structure_data: Dict, pr_insights: List[Dict], lessons: List[Dict], dependencies: Dict = None) -> str:
        """Format risk factors"""
        lines = ["**Risk Factors**:"]

        risks = []

        # Complexity risk
        arch = structure_data.get("architecture", "")
        if arch == "Kubernetes Operator":
            crds = structure_data.get("api_types", [])
            if len(crds) > 3:
                risks.append({
                    "type": "Complexity",
                    "description": f"Multiple CRDs ({len(crds)}) increase integration complexity",
                    "mitigation": "Carefully plan API changes and backwards compatibility"
                })

        # Historical risk from lessons
        if lessons:
            risks.append({
                "type": "Historical",
                "description": "Component has encountered issues in the past",
                "mitigation": "Review closed issues and apply lessons learned"
            })

        # Integration risk
        packages = structure_data.get("key_packages", [])
        if any("client" in p.get("name", "").lower() for p in packages):
            risks.append({
                "type": "Integration",
                "description": "External API dependencies require careful coordination",
                "mitigation": "Verify API contracts and handle failures gracefully"
            })

        # Dependency risks (Phase 2)
        if dependencies and dependencies.get("risks"):
            for dep_risk in dependencies["risks"][:2]:  # Add top 2 dependency risks
                risks.append(dep_risk)

        # Format risks
        if risks:
            for risk in risks[:5]:  # Increased from 3 to 5 to accommodate dependency risks
                lines.append(f"- **{risk['type']}**: {risk['description']}")
                lines.append(f"  - **Mitigation**: {risk['mitigation']}")
        else:
            lines.append("- **Standard risks**: Apply OpenShift development best practices")

        return "\n".join(lines) + "\n"

    def _format_upstream_analysis(
        self,
        repo_data: Dict,
        upstream_structure: Dict,
        upstream_pr_insights: List[Dict],
        upstream_adrs: List[Dict],
        downstream_structure: Dict
    ) -> str:
        """Format upstream repository analysis"""
        lines = ["**Upstream Analysis**:\n"]

        upstream = repo_data.get("upstream", {})
        upstream_name = upstream.get("name", "Unknown")

        lines.append(f"*Analysis of upstream repository: {upstream_name}*\n")

        # Architecture comparison
        if upstream_structure:
            downstream_arch = downstream_structure.get("architecture", "Unknown")
            upstream_arch = upstream_structure.get("architecture", "Unknown")

            lines.append("**Architecture Comparison**:")
            lines.append(f"- Downstream: {downstream_arch}")
            lines.append(f"- Upstream: {upstream_arch}")

            if downstream_arch != upstream_arch:
                lines.append(f"  - *Note: Different architectures may indicate OpenShift-specific adaptations*")
            lines.append("")

        # Upstream implementation patterns
        if upstream_pr_insights:
            lines.append("**Upstream Implementation Patterns**:")
            for insight in upstream_pr_insights[:2]:
                pr = insight.get("pr", {})
                extracted = insight.get("insights", {})

                pr_num = pr.get("number")
                pr_title = pr.get("title", "")

                lines.append(f"- Upstream PR #{pr_num}: {pr_title}")

                design_sections = extracted.get("design_sections", [])
                if design_sections:
                    design_snippet = design_sections[0][:150].replace('\n', ' ')
                    lines.append(f"  - Pattern: {design_snippet}...")

            lines.append("")

        # Upstream ADRs
        if upstream_adrs:
            lines.append("**Upstream Architecture Decisions**:")
            for adr in upstream_adrs[:2]:
                adr_name = adr.get("name", "").replace(".md", "")
                adr_url = adr.get("url", "")
                lines.append(f"- {adr_name}: {adr_url}")
            lines.append("")

        # Adoption recommendations
        lines.append("**Upstream Adoption Considerations**:")
        if upstream_structure and downstream_structure:
            # Compare CRD counts
            upstream_crds = len(upstream_structure.get("api_types", []))
            downstream_crds = len(downstream_structure.get("api_types", []))

            if upstream_crds > downstream_crds:
                lines.append(f"- Upstream has {upstream_crds} CRDs vs downstream {downstream_crds} - consider adopting additional APIs")
            elif upstream_crds < downstream_crds:
                lines.append(f"- Downstream has {downstream_crds} CRDs vs upstream {upstream_crds} - OpenShift-specific extensions present")

        if upstream_pr_insights:
            lines.append("- Review upstream PRs for proven implementation patterns")
            lines.append("- Consider contributing OpenShift enhancements back to upstream")

        lines.append("")

        return "\n".join(lines)

    def _format_recommended_approach(
        self,
        repo_data: Dict,
        structure_data: Dict,
        pr_insights: List[Dict],
        upstream_structure: Dict = None,
        upstream_pr_insights: List[Dict] = None
    ) -> str:
        """Format recommended approach for RFE implementation"""
        lines = ["**Recommended Approach for RFE Implementation**:"]

        arch = structure_data.get("architecture", "")
        downstream = repo_data.get("downstream", {})
        repo_name = downstream.get("name", "the component")

        # Architecture-specific guidance
        if arch == "Kubernetes Operator":
            lines.append(f"- Follow Kubernetes Operator pattern established in {repo_name}")
            lines.append("- Consider CRD API changes carefully for backwards compatibility")

        # Reuse from PRs
        if pr_insights:
            top_pr = pr_insights[0].get("pr", {})
            pr_num = top_pr.get("number")
            if pr_num:
                lines.append(f"- Review downstream PR #{pr_num} for similar implementation patterns")

        # Upstream guidance
        if upstream_pr_insights:
            top_upstream_pr = upstream_pr_insights[0].get("pr", {})
            upstream_pr_num = top_upstream_pr.get("number")
            if upstream_pr_num:
                lines.append(f"- Review upstream PR #{upstream_pr_num} for original design approach")
                lines.append("- Consider adopting upstream patterns where applicable to OpenShift")

        if upstream_structure:
            lines.append("- Align with upstream architecture where possible to ease future updates")

        # General guidance
        lines.append("- Apply OpenShift coding standards and test coverage requirements")
        lines.append("- Consider upgrade/downgrade scenarios")

        # Avoid pitfalls
        lines.append("- Avoid: Making breaking API changes without deprecation period")
        lines.append("- Avoid: Insufficient error handling for external dependencies")
        if upstream_structure:
            lines.append("- Avoid: Diverging significantly from upstream without strong justification")

        return "\n".join(lines)

    def _format_rfe_related_files(self, rfe_related_files: Dict) -> str:
        """Format RFE-specific code files (Phase 2)"""
        lines = ["**RFE-Specific Code Files**:\n"]

        has_content = False

        # Flag definitions
        if rfe_related_files.get("flag_definitions"):
            lines.append("*Flag Definitions*:")
            for item in rfe_related_files["flag_definitions"][:5]:
                lines.append(f"- `{item['flag']}` in [{item['file']}]({item['url']})")
            lines.append("")
            has_content = True

        # CRD definitions
        if rfe_related_files.get("crd_definitions"):
            lines.append("*CRD Definitions*:")
            for item in rfe_related_files["crd_definitions"][:5]:
                lines.append(f"- `{item['crd']}` in [{item['file']}]({item['url']})")
            lines.append("")
            has_content = True

        # Config files
        if rfe_related_files.get("config_files"):
            lines.append("*Configuration Files*:")
            for item in rfe_related_files["config_files"][:5]:
                lines.append(f"- [{item['file']}]({item['url']})")
            lines.append("")
            has_content = True

        # Controller files
        if rfe_related_files.get("controller_files"):
            lines.append("*Controller Files*:")
            for item in rfe_related_files["controller_files"][:5]:
                lines.append(f"- [{item['file']}]({item['url']})")
            lines.append("")
            has_content = True

        # Test files
        if rfe_related_files.get("test_files"):
            lines.append("*Related Test Files*:")
            for item in rfe_related_files["test_files"][:5]:
                lines.append(f"- [{item['file']}]({item['url']})")
            lines.append("")
            has_content = True

        if not has_content:
            return ""

        return "\n".join(lines) + "\n"

    def _format_bug_patterns(self, bug_patterns: List[Dict]) -> str:
        """Format bug patterns and lessons (Phase 2)"""
        if not bug_patterns:
            return ""

        lines = ["**Lessons from Related Bugs**:\n"]

        for pattern in bug_patterns[:5]:
            bug_key = pattern.get("bug_key", "")
            summary = pattern.get("summary", "")
            lesson = pattern.get("lesson", "")
            url = pattern.get("url", "")

            lines.append(f"- [{bug_key}]({url}): {summary}")
            if lesson:
                # Truncate lesson to first 200 chars
                lesson_short = lesson[:200] + "..." if len(lesson) > 200 else lesson
                lines.append(f"  - *Lesson*: {lesson_short}")

        return "\n".join(lines) + "\n"

    def _format_dependencies(self, dependencies: Dict) -> str:
        """Format dependency analysis (Phase 2)"""
        lines = ["**Dependency Analysis**:\n"]

        # Show total dependencies count
        all_deps = dependencies.get("dependencies", [])
        if all_deps:
            lines.append(f"*Total Dependencies*: {len(all_deps)}\n")

        # Show risks
        risks = dependencies.get("risks", [])
        if risks:
            lines.append("*Identified Risks*:")
            for risk in risks:
                risk_type = risk.get("type", "")
                severity = risk.get("severity", "medium")
                description = risk.get("description", "")
                mitigation = risk.get("mitigation", "")

                severity_icon = "🔴" if severity == "high" else "🟡"
                lines.append(f"- {severity_icon} **{risk_type}**: {description}")
                if mitigation:
                    lines.append(f"  - *Mitigation*: {mitigation}")

            lines.append("")

        # Show recommendations
        recommendations = dependencies.get("recommendations", [])
        if recommendations:
            lines.append("*Recommendations*:")
            for rec in recommendations[:5]:
                rec_type = rec.get("type", "")
                recommendation = rec.get("recommendation", "")
                lines.append(f"- **{rec_type}**: {recommendation}")

            lines.append("")

        return "\n".join(lines) + "\n"

    # Helper methods

    def _extract_pattern_name(self, design_text: str) -> str:
        """Extract a pattern name from design text"""
        # Look for common pattern indicators
        if "controller" in design_text.lower():
            return "Controller Pattern"
        elif "reconcil" in design_text.lower():
            return "Reconciliation Loop"
        elif "cache" in design_text.lower() or "caching" in design_text.lower():
            return "Caching Strategy"
        elif "retry" in design_text.lower() or "backoff" in design_text.lower():
            return "Retry/Backoff Mechanism"
        elif "watch" in design_text.lower():
            return "Watch/Event Pattern"
        else:
            return "Implementation Pattern"

    def _infer_package_purpose(self, pkg_name: str) -> str:
        """Infer package purpose from name"""
        pkg_lower = pkg_name.lower()

        if "controller" in pkg_lower:
            return "Controller implementations"
        elif "api" in pkg_lower:
            return "API type definitions"
        elif "client" in pkg_lower:
            return "Client interfaces"
        elif "util" in pkg_lower or "helper" in pkg_lower:
            return "Utility functions"
        elif "webhook" in pkg_lower:
            return "Webhook handlers"
        elif "config" in pkg_lower:
            return "Configuration management"
        else:
            return "Core logic"

    def _extract_lesson_snippet(self, body: str) -> str:
        """Extract a lesson snippet from issue body"""
        import re

        # Find sentences with "lesson" or "learned"
        sentences = re.split(r'[.!?]\n', body)
        for sentence in sentences:
            if "lesson" in sentence.lower() or "learned" in sentence.lower():
                clean = sentence.strip()
                if len(clean) > 30:
                    return clean[:200]

        return ""


def main():
    """Test the synthesizer"""
    import sys

    if len(sys.argv) < 2:
        print("Usage: context_synthesizer.py <component-name>")
        print("\nThis is typically called by gather_component_context.py")
        sys.exit(1)

    # Example data
    component_name = sys.argv[1]

    repo_data = {
        "component": component_name,
        "downstream": {
            "name": f"openshift/{component_name}-operator",
            "description": "OpenShift operator for managing component"
        },
        "upstream": {
            "name": f"upstream/{component_name}"
        },
        "related": []
    }

    structure_data = {
        "architecture": "Kubernetes Operator",
        "key_packages": [
            {"name": "controllers"},
            {"name": "api"}
        ],
        "api_types": [
            {"file": "component_v1_custom.yaml"}
        ],
        "controllers": ["component_controller.go"]
    }

    pr_insights = []
    adrs = []
    lessons = []

    synthesizer = ContextSynthesizer()
    context = synthesizer.synthesize_component_context(
        component_name,
        repo_data,
        structure_data,
        pr_insights,
        adrs,
        lessons
    )

    print(context)


if __name__ == "__main__":
    main()
