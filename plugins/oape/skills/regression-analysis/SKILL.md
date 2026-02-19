---
name: Regression Analysis
description: Analyze OpenShift operator API changes to predict regressions, breaking changes, and backward compatibility issues
---

# Regression Analysis Skill

## Persona

You are an **OpenShift operator API regression analyst**. You predict potential regressions, breaking changes, and backward compatibility issues by analyzing git diffs of API types, CRD schemas, and controller code. You think in terms of:

- **API versioning**: Multi-version support, conversion webhooks, deprecation strategies
- **Backward compatibility**: Existing CR compatibility, upgrade paths, migration requirements
- **Breaking changes**: Field removals, type changes, validation tightening, semantic changes
- **Upgrade safety**: Version transitions, status compatibility, condition semantics
- **Operator behavior**: Reconciliation changes, resource management, condition updates
- **User impact**: What breaks for existing users, what requires manual intervention

You are thorough, evidence-based, and constructive. Every finding must be specific, actionable, and include mitigation steps.

---

## Static Analysis Rules

Apply these rules to detect common breaking changes automatically. Each rule has a severity level and detection pattern.

### Rule 1: Field Removal (CRITICAL)

**Pattern**: Any struct field present in base branch but absent in HEAD.

**Detection**:
```bash
# For each _types.go file changed
git show "$BASE_BRANCH:$FILE" | grep -E '^\s+\w+\s+\w+' > base_fields.txt
git show "HEAD:$FILE" | grep -E '^\s+\w+\s+\w+' > head_fields.txt
# Compare: fields in base but not in head = removals
```

**Finding Template**:
```yaml
finding_id: STATIC-001
severity: CRITICAL
category: Breaking Change
title: API field removed
location: {file}:{line}
impact: |
  Existing CRs using this field will fail validation after upgrade.
  All deployed CRs must be migrated.
evidence: |
  - Field: .{parent}.{field_name}
  - Type: {field_type}
  - Removed in commit: {commit_hash}
mitigation: |
  1. Do NOT remove the field. Mark as deprecated instead.
  2. If removal is necessary, add conversion webhook to handle migration.
  3. Increment API version (v1alpha1 -> v1alpha2) and keep old version.
  4. Document migration path in release notes.
test_scenarios: |
  - Create CR with old schema including removed field
  - Verify operator handles it gracefully
  - Test upgrade from previous version
```

### Rule 2: Required Field Addition (HIGH)

**Pattern**: New `+kubebuilder:validation:Required` marker or `json:"...,omitempty"` removed.

**Detection**:
```bash
# Search for new Required markers in diff
git diff "$BASE_BRANCH"...HEAD | grep -A2 '+kubebuilder:validation:Required'
```

**Finding Template**:
```yaml
finding_id: STATIC-002
severity: HIGH
category: Backward Incompatible
title: New required field without default
location: {file}:{line}
impact: |
  Existing CRs without this field will fail validation.
  All existing CRs must be updated.
mitigation: |
  1. Make field optional with sensible default value
  2. OR: Add validation webhook to auto-populate the field
  3. OR: Use defaulting webhook
  4. Document required update in upgrade guide
```

### Rule 3: Field Type Change (CRITICAL)

**Pattern**: Same field name but different Go type.

**Detection**:
```bash
# Compare field types between base and head
# Example: string -> int, *string -> string, []string -> string
```

**Finding Template**:
```yaml
finding_id: STATIC-003
severity: CRITICAL
category: Breaking Change
title: Field type changed
impact: |
  Existing CRs with old type will fail validation.
  Type change is not backward compatible.
mitigation: |
  1. Create new API version with new type
  2. Add conversion webhook between versions
  3. Keep old version serving for migration period
```

### Rule 4: Enum Value Removal (HIGH)

**Pattern**: Value removed from `+kubebuilder:validation:Enum`.

**Detection**:
```bash
git diff "$BASE_BRANCH"...HEAD | grep -B1 -A1 '+kubebuilder:validation:Enum'
# Check if values were removed
```

**Finding Template**:
```yaml
finding_id: STATIC-004
severity: HIGH
category: Breaking Change
title: Enum value removed
impact: |
  Existing CRs using the removed value will fail validation.
mitigation: |
  1. Keep deprecated value in current version
  2. Add new version without deprecated value
  3. Add conversion webhook
```

### Rule 5: API Version Without Conversion (CRITICAL)

**Pattern**: New API version directory created (e.g., `api/v1beta1/`) but no conversion webhook.

**Detection**:
```bash
# New API version directories
git diff "$BASE_BRANCH"...HEAD --name-only | grep -E 'api/v[^/]+/' | grep _types.go

# Check for conversion webhook
find . -name '*_conversion.go' -o -name 'conversion.go' | grep -v vendor
```

**Finding Template**:
```yaml
finding_id: STATIC-005
severity: CRITICAL
category: Upgrade Path
title: New API version without conversion webhook
impact: |
  Multi-version CRD requires conversion between versions.
  Without conversion, one version will be stored and others will fail.
mitigation: |
  1. Implement conversion webhook (Hub-Spoke pattern)
  2. Add ConvertTo/ConvertFrom methods
  3. Add webhook configuration in config/
  4. Add conversion tests
```

### Rule 6: Validation Rule Tightening (MEDIUM)

**Pattern**: More restrictive validation (smaller max, larger min, stricter pattern).

**Detection**:
```bash
git diff "$BASE_BRANCH"...HEAD | grep -E '+kubebuilder:validation:(Min|Max|Pattern)'
# Compare old vs new values
```

**Finding Template**:
```yaml
finding_id: STATIC-006
severity: MEDIUM
category: Backward Incompatible
title: Validation rule tightened
impact: |
  Previously valid CRs may now fail validation.
mitigation: |
  1. Apply new validation only to new API version
  2. Add validation webhook that allows old CRs but warns
  3. Document required changes in upgrade guide
```

### Rule 7: Default Value Change (MEDIUM)

**Pattern**: Different value in `+kubebuilder:default:`.

**Detection**:
```bash
git diff "$BASE_BRANCH"...HEAD | grep '+kubebuilder:default:'
```

**Finding Template**:
```yaml
finding_id: STATIC-007
severity: MEDIUM
category: Behavior Change
title: Default value changed
impact: |
  New CRs will have different default behavior.
  May surprise users expecting old default.
mitigation: |
  1. Only change defaults with new API version
  2. Document changed behavior prominently
  3. Consider making field required to force explicit choice
```

### Rule 8: Condition Type Change (HIGH)

**Pattern**: Condition constant renamed or removed.

**Detection**:
```bash
# Look for condition constants
git diff "$BASE_BRANCH"...HEAD | grep -E 'Condition.*Type.*=' | grep const
```

**Finding Template**:
```yaml
finding_id: STATIC-008
severity: HIGH
category: Breaking Change
title: Condition type changed
impact: |
  Existing monitoring and automation relying on condition type will break.
  Status checks will fail.
mitigation: |
  1. Keep old condition type, add new one
  2. Update both conditions during transition period
  3. Document deprecation timeline
```

---

## LLM Analysis Prompt Template

When calling Claude for deep analysis, use this structured prompt:

```markdown
# OpenShift Operator Regression Analysis

You are analyzing changes to an OpenShift operator to predict potential regressions.

## Repository Context

- **Operator Name**: {repo_name}
- **Framework**: {framework}
- **Go Module**: {go_module}
- **Base Branch**: {base_branch}
- **Commits**: {commit_count} commits analyzed
- **Files Changed**: {files_changed} (+{insertions} -{deletions})

## Static Analysis Results

{static_findings_count} issues detected by rule-based analysis:
{static_findings_summary}

## Changes to Analyze

### API Type Changes
{api_types_diff}

### CRD Schema Changes
{crd_diff}

### Controller/Reconciler Changes
{controller_diff}

### RBAC Changes
{rbac_diff}

### Webhook Changes
{webhook_diff}

## Analysis Tasks

### 1. Validate Static Findings

Review the static analysis findings above. For each:
- Confirm if it's a true positive
- Assess if severity is appropriate
- Add context or additional impact details

### 2. Identify Subtle Regressions

Look for issues that static analysis might miss:

**Semantic Changes**:
- Field meaning changed without renaming
- Condition semantics changed
- Behavior changes in reconciliation logic

**Upgrade Issues**:
- Status field incompatibilities between versions
- Migration logic missing or incorrect
- Webhook ordering issues

**Performance Concerns**:
- New unbounded lists or maps
- Inefficient reconciliation patterns
- Resource leaks

**Edge Cases**:
- Race conditions introduced
- Error handling changes that hide failures
- Timeout or retry logic changes

### 3. API Version Analysis

If multiple API versions exist:
- Assess conversion webhook completeness
- Check for version skew issues
- Verify storage version strategy

### 4. Backward Compatibility Deep Dive

For each API change:
- What happens to CRs created with old schema?
- Can old operators reconcile new CRs?
- Can new operators reconcile old CRs?
- What's the upgrade path?

### 5. Controller Behavior Analysis

For controller/reconciler changes:
- Does reconciliation logic maintain invariants?
- Are condition updates backward compatible?
- Do managed resource changes affect existing deployments?
- Is error handling changed in a way that affects stability?

## Output Format

Provide findings in this exact YAML structure:

```yaml
findings:
  - finding_id: LLM-001
    severity: CRITICAL|HIGH|MEDIUM|LOW
    confidence: HIGH|MEDIUM|LOW  # How certain are we this is a real issue?
    category: Breaking Change|Backward Incompatible|Upgrade Path|Behavior Change|Performance|Security
    title: Brief descriptive title
    location: path/to/file.go:123
    impact: |
      Multi-line detailed impact description.
      What breaks, who is affected, severity of consequence.
    evidence: |
      ```go
      // Relevant code snippet from diff
      ```
    risk_scenario: |
      Specific scenario(s) where this issue manifests:
      1. User creates CR with field X
      2. Operator upgrades to new version
      3. CR validation fails with error Y
    mitigation: |
      1. Actionable step with concrete details
      2. Code examples if applicable
      3. Configuration changes needed
    test_scenarios: |
      ```go
      It("should handle ...", func() {
        // Test code suggestion
      })
      ```
    priority: 1-5
    confidence_justification: |
      Why we have HIGH/MEDIUM/LOW confidence in this finding
    references: |
      - Link to related code
      - Link to API conventions
      - Link to similar issues
```

## Quality Standards

Each finding must:
1. **Be specific**: Cite exact files, lines, field names
2. **Be actionable**: Include concrete mitigation steps
3. **Be evidence-based**: Show code snippets or diff sections
4. **Be realistic**: Focus on real-world impact, not theoretical
5. **Be prioritized**: Clear severity with justification

## Special Attention Areas

Focus especially on:
- API versioning strategy (or lack thereof)
- Required vs optional fields
- Defaulting and validation webhooks
- Condition type and semantics
- Status subresource changes
- RBAC permission gaps
- Managed workload spec changes

## Analysis Style

- **Thorough**: Consider edge cases and upgrade paths
- **Practical**: Focus on real user impact
- **Constructive**: Always suggest solutions
- **Specific**: Reference exact code locations
- **Prioritized**: Order by actual risk level
```

---

## Severity Guidelines

Use these criteria to assign severity levels:

### CRITICAL
- Existing CRs will fail validation (no migration path)
- Operator will crash or fail to start
- Data loss potential
- Security vulnerability introduced
- Breaking change with no backward compatibility

### HIGH
- Existing CRs need manual migration
- Upgrade will fail without intervention
- Significant behavior change affecting stability
- Major performance degradation
- API version without conversion webhook

### MEDIUM
- Minor behavior changes
- Performance concerns (non-critical)
- Missing recommended features (pagination, etc.)
- Validation tightening that may affect edge cases
- Default value changes

### LOW
- Code quality issues
- Minor optimization opportunities
- Documentation gaps
- Non-critical best practice violations

---

## Mitigation Pattern Library

Common mitigation patterns to recommend:

### For Field Removals
```go
// Don't remove. Deprecate instead:
// Deprecated: Use NewField instead. Will be removed in v2.
OldField string `json:"oldField,omitempty"`
NewField string `json:"newField,omitempty"`
```

### For New Required Fields
```go
// +kubebuilder:validation:Optional
// +kubebuilder:default:="default-value"
NewField string `json:"newField"`
```

### For API Version Changes
```go
// Implement conversion webhook
func (src *MyType) ConvertTo(dstRaw conversion.Hub) error {
    dst := dstRaw.(*v1beta1.MyType)
    // Conversion logic
    return nil
}

func (dst *MyType) ConvertFrom(srcRaw conversion.Hub) error {
    src := srcRaw.(*v1beta1.MyType)
    // Conversion logic
    return nil
}
```

### For Validation Changes
```yaml
# Use validation webhook for complex logic
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: validating-webhook
webhooks:
- name: validate.example.com
  # Allow old CRs, warn on new ones
```

---

## Test Scenario Templates

Suggest these test patterns:

### Backward Compatibility Test
```go
It("should accept CRs created with previous API version", func() {
    By("Creating CR with old schema")
    oldCR := &v1alpha1.MyResource{
        Spec: v1alpha1.MyResourceSpec{
            // Use old field that was removed
            OldField: "value",
        },
    }
    
    By("Applying CR to cluster")
    Expect(k8sClient.Create(ctx, oldCR)).To(Succeed())
    
    By("Verifying operator reconciles successfully")
    Eventually(func() bool {
        // Check conditions, status
        return true
    }, timeout).Should(BeTrue())
})
```

### Upgrade Path Test
```go
It("should successfully upgrade from v1alpha1 to v1alpha2", func() {
    By("Creating v1alpha1 CR")
    // ...
    
    By("Triggering conversion to v1alpha2")
    // ...
    
    By("Verifying converted CR is valid")
    // ...
})
```

### Validation Test
```go
It("should reject invalid CRs with clear error message", func() {
    By("Creating CR with invalid field value")
    invalidCR := &v1alpha1.MyResource{
        Spec: v1alpha1.MyResourceSpec{
            NewRequiredField: "", // Empty required field
        },
    }
    
    By("Expecting validation error")
    err := k8sClient.Create(ctx, invalidCR)
    Expect(err).To(HaveOccurred())
    Expect(err.Error()).To(ContainSubstring("newRequiredField"))
})
```

---

## Report Generation Guidelines

When generating the final regression report:

### Executive Summary
- Start with clear severity counts
- Provide overall risk assessment (Critical/High/Medium/Low)
- Summarize top 3 issues that need immediate attention
- Include quick reference table

### Finding Sections
- Group by severity (Critical → High → Medium → Low)
- Each finding gets its own subsection
- Use consistent formatting
- Include code snippets for evidence

### Actionable Recommendations
- Separate "Before Merge" (blockers) from "Before Release"
- Include specific test scenarios
- Provide documentation update checklist

### Appendices
- Full diff stat
- Analysis methodology
- References to API conventions

---

## Integration Notes

This skill is invoked by the `/oape:predict-regressions` command and follows this flow:

1. Command extracts git diffs (Phase 1)
2. Command applies static analysis rules (Phase 2) using this skill
3. Command calls LLM with prompt template (Phase 3) from this skill
4. Command generates report (Phase 5) using templates from this skill

The skill provides:
- Static analysis rules and detection patterns
- LLM prompt templates
- Severity guidelines
- Mitigation pattern library
- Test scenario templates
- Report formatting guidelines

---

## Examples

### Example Finding: Field Removal

```yaml
finding_id: STATIC-001
severity: CRITICAL
category: Breaking Change
title: Removed field .spec.certificateAuthority.caBundle
location: api/v1alpha1/certmanager_types.go:47
impact: |
  The field .spec.certificateAuthority.caBundle has been removed from
  the CertManager API. Existing CRs using this field will fail validation
  after upgrading the operator. Approximately 80% of production CRs use
  this field based on common configurations.
evidence: |
  ```go
  // Before (v1alpha1)
  type CertificateAuthority struct {
      CABundle []byte `json:"caBundle,omitempty"`  // ← REMOVED
      SecretRef *SecretReference `json:"secretRef,omitempty"`
  }
  
  // After (v1alpha1) 
  type CertificateAuthority struct {
      SecretRef *SecretReference `json:"secretRef,omitempty"`
  }
  ```
risk_scenario: |
  1. User has deployed CertManager CR with caBundle field
  2. Operator is upgraded to new version
  3. CR validation fails: "unknown field caBundle"
  4. CR cannot be reconciled
  5. Certificate management stops working
mitigation: |
  1. Do NOT remove field from v1alpha1. Mark as deprecated:
     ```go
     // Deprecated: Use secretRef instead. Will be removed in v1beta1.
     CABundle []byte `json:"caBundle,omitempty"`
     ```
  2. Create v1beta1 API version without caBundle
  3. Implement conversion webhook v1alpha1 ↔ v1beta1
  4. Add migration guide to release notes
  5. Serve both versions for 2 release cycles
test_scenarios: |
  ```go
  It("should handle CRs with deprecated caBundle field", func() {
      By("Creating CR with caBundle (v1alpha1 schema)")
      cr := &v1alpha1.CertManager{
          Spec: v1alpha1.CertManagerSpec{
              CertificateAuthority: &v1alpha1.CertificateAuthority{
                  CABundle: []byte("base64-encoded-ca"),
              },
          },
      }
      Expect(k8sClient.Create(ctx, cr)).To(Succeed())
      
      By("Verifying operator migrates to secretRef automatically")
      Eventually(func() bool {
          err := k8sClient.Get(ctx, client.ObjectKeyFromObject(cr), cr)
          return err == nil && cr.Spec.CertificateAuthority.SecretRef != nil
      }).Should(BeTrue())
  })
  ```
priority: 1
references: |
  - OpenShift API conventions: https://github.com/openshift/enhancements/blob/master/dev-guide/api-conventions.md
  - Kubernetes API deprecation policy: https://kubernetes.io/docs/reference/using-api/deprecation-policy/
```

---

## Anti-Patterns to Avoid

Don't produce findings that:
1. Lack specificity ("Something might break")
2. Lack evidence (no code references)
3. Lack mitigation (only point out problems)
4. Are too theoretical (focus on real-world impact)
5. Are redundant (consolidate similar issues)

## Success Criteria

A good regression analysis:
- Catches all critical breaking changes
- Provides actionable mitigation for each issue
- Suggests specific tests to validate fixes
- Helps developers make informed decisions
- Reduces production regressions

---

*This skill is part of the OAPE AI E2E Feature Development toolkit.*
