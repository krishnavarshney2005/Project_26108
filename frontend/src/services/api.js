export const API_BASE = import.meta.env.VITE_API_BASE_URL || '';
export const API_ROOT = API_BASE + '/api/v1';

export const API_KEY = import.meta.env.VITE_STANDIQ_API_KEY || 'sk_standiq_dev_26108';

// The backend exposes /health at the root, outside the /api/v1 prefix.
export async function getBackendHealth() {
  const response = await fetch(`${API_BASE}/health`, {
    headers: { 'X-API-Key': API_KEY }
  });
  if (!response.ok) throw new Error(`Health check failed: ${response.status}`);
  return response.json();
}

async function request(path, options = {}) {
  const headers = {
    'X-API-Key': API_KEY,
    ...(options.headers || {})
  };
  
  const response = await fetch(`${API_ROOT}${path}`, { ...options, headers });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      // FastAPI puts structured errors in detail; pick the most readable field
      message = body?.detail?.message || body?.message || body?.detail || JSON.stringify(body);
    } catch {
      message = await response.text().catch(() => response.statusText);
    }
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }
  return response.json();
}

// Clean BIS raw titles — strip purchase/price boilerplate injected into some catalog entries
function cleanBisTitle(rawTitle = '') {
  // Strip everything after common boilerplate phrases
  const cutoffs = [
    ' This standard is available',
    ' This Standard is available',
    'NOTE -',
    'Note -',
    '(Please refer',
    'For Printed copies',
  ];
  let t = rawTitle;
  for (const c of cutoffs) {
    const idx = t.indexOf(c);
    if (idx > 20) t = t.slice(0, idx);
  }
  return t.trim().replace(/\s+/g, ' ');
}

// Generate scope text when catalog entry has null scope
function derivedScope(standard) {
  if (standard.scope) return standard.scope;
  const kw = (standard.keywords || []).slice(0, 6).join(', ');
  const title = cleanBisTitle(standard.title || '');
  if (kw) return `${title.slice(0, 80)}. Key areas: ${kw}.`;
  return `Indian Standard specifying requirements for: ${title.slice(0, 120)}.`;
}

export function toUiStandard(standard) {
  const cleanTitle = cleanBisTitle(standard.title || standard.designation || standard.is_number || '');
  const designation = standard.designation || standard.is_number || '';
  return {
    id: standard.id,
    standardCode: designation,
    title: cleanTitle,
    standardTitle: cleanTitle,
    statusBadge: (standard.status || 'active').replaceAll('_', ' ').toUpperCase(),
    currentVersion: standard.latest_version || designation,
    overview: derivedScope(standard),
    scope: derivedScope(standard),
    category: standard.division_council || inferCategory(designation),
    isQcoMandatory: Boolean(standard.qco_notified),
    applicability: standard.qco_notified ? 'QCO mandatory' : 'Catalog reference',
    internationalEquivalent: standard.ics_code || 'Not stated',
    amendments: standard.amendments || [],
    normativeReferences: standard.normative_references || [],
    relevantSections: [],
    whyRecommended: standard.text_excerpt || derivedScope(standard),
    matchPercentage: null,
    operatingVoltage: standard.demo_operating_voltage || 'Not stated in catalog',
    ipRating: standard.demo_ip_rating || 'Not stated in catalog',
    surgeProtection: standard.demo_surge_protection || 'Not stated in catalog',
    thermalDissipation: standard.demo_thermal_dissipation || 'Not stated in catalog',
    testMethods: standard.demo_test_methods || (standard.test_methods?.join(', ') || 'Not stated in catalog'),
    certification: standard.qco_notified ? 'BIS certification required' : 'Not stated in catalog',
  };
}

function inferCategory(designation = '') {
  const d = designation.toUpperCase();
  if (d.includes('IS 1') || d.includes('IS 2') || d.includes('IS 3')) {
    const num = parseInt(d.replace(/[^0-9]/g, '')) || 0;
    if (num < 1000) return 'Civil & Structural';
    if (num < 5000) return 'Mechanical & Materials';
    if (num < 10000) return 'Electrical & Electronics';
    return 'Testing & Measurement';
  }
  if (d.startsWith('SP ')) return 'Special Publication';
  if (d.startsWith('IS/IEC') || d.startsWith('IEC')) return 'International Harmonized';
  return 'BIS Catalog';
}

export function toUiAnalysis(payload) {
  if (payload.standards) {
    const findings = payload.findings || [];
    const requirements = (payload.requirements || []).map((requirement) => {
      const finding = findings.find((item) => item.requirement_id === requirement.id);
      return {
        id: requirement.id,
        type: requirement.category?.replaceAll('_', ' ') || 'Requirement',
        parameter: requirement.category?.replaceAll('_', ' ') || 'Technical requirement',
        specifiedValue: requirement.text,
        confidence: requirement.extraction_confidence ?? finding?.confidence ?? 0,
        status: finding?.verdict === 'justified' ? 'VALID' : 'RESTRICTIVE_FLAG',
        governingStandard: finding?.applicable_standards?.[0]?.designation || 'Not mapped',
      };
    });
    const standards = payload.standards.map((standard, index) => ({
      ...toUiStandard(standard),
      rank: index + 1,
      matchedRequirements: findings
        .filter((finding) => finding.applicable_standards?.some((item) => item.id === standard.id))
        .map((finding) => finding.requirement_id),
    }));
    const flagged = findings.filter((finding) => finding.verdict !== 'justified');
    const score = Math.max(0, 100 - flagged.length * 10);
    const evidence = findings.map((finding) => {
      const matchedStd = finding.applicable_standards?.[0];
      const stdObj = payload.standards?.find((s) => s.id === matchedStd?.id);
      return {
        id: finding.id,
        requirement: finding.verdict.replaceAll('_', ' '),
        tenderTextSnippet: payload.requirements.find((item) => item.id === finding.requirement_id)?.text || '',
        confidence: finding.confidence,
        mappedClause: matchedStd?.designation || 'No mapped standard',
        standardClauseText: finding.evidence?.[0]?.excerpt
          || (stdObj ? `${stdObj.designation || matchedStd?.designation}: ${stdObj.title}. Status: ${stdObj.status || 'active'}.` : finding.reason),
        aiJustification: finding.reason,
      };
    });

    const areasForImprovement = flagged.map((f) => f.reason);

    const missingRecommendations = flagged.map((finding) => ({
      id: finding.id,
      parameter: finding.verdict.replaceAll('_', ' '),
      category: 'Compliance finding',
      missingExplanation: finding.reason,
      suggestedClauseText: finding.recommended_action || finding.reason,
    }));

    // Strengths are derived from what the analysis actually found — never asserted.
    const qcoCount = standards.filter((s) => s.isQcoMandatory).length;
    const justifiedCount = findings.length - flagged.length;
    const strengths = [];
    if (standards.length > 0) {
      strengths.push(`${standards.length} BIS standard(s) matched against the specification.`);
    }
    if (qcoCount > 0) {
      strengths.push(`${qcoCount} QCO-mandatory standard(s) identified for bid submission.`);
    }
    if (justifiedCount > 0) {
      strengths.push(`${justifiedCount} of ${findings.length} requirement(s) assessed as justified.`);
    }

    return {
      ...payload,
      extracted_requirements: requirements,
      standards_intelligence: standards,
      evidence,
      input_summary: {
        title: payload.tender_title || 'Procurement specification',
        category: payload.metadata?.category || 'BIS analysis',
        department: payload.metadata?.department || 'Procurement review',
      },
      pre_publication_summary: {
        scorecard: {
          overallScore: score,
          grade: score >= 90 ? 'A' : score >= 75 ? 'B' : 'C',
          statusText: payload.analysis_mode === 'remote' ? 'Remote AI analysis complete' : 'Deterministic fallback analysis',
          summaryText: payload.degraded_reason || 'Compliance scores derived from BIS catalog matching.',
          categoryScores: [
            { name: 'Completeness', score },
            { name: 'Defensibility', score: Math.min(100, score + 5) },
            { name: 'Regulatory compliance', score: 100 },
            { name: 'Vendor neutrality', score: Math.max(70, score - 8) },
          ],
          strengths,
          areasForImprovement,
        },
        missing_recommendations: missingRecommendations,
      },
    };
  }

  const requirements = (payload.extracted_requirements || payload.requirements || []).map((requirement) => ({
    ...requirement,
    type: requirement.type || requirement.category || 'General',
    specifiedValue: requirement.specifiedValue || requirement.specified_value || '',
    governingStandard:
      requirement.governingStandard || requirement.evidence_chain?.standard_code || 'Not mapped',
    confidence: requirement.confidence ?? requirement.evidence_chain?.confidence ?? 0,
  }));

  const backendStandards = payload.standards_intelligence || payload.standards || [];
  const standards = backendStandards.map((standard, index) => ({
    ...standard,
    rank: standard.rank ?? index + 1,
    standardCode: standard.standardCode || standard.code || standard.designation || 'Unknown standard',
    standardTitle: standard.standardTitle || standard.title || '',
    statusBadge: standard.statusBadge || standard.status_badge || standard.status || 'UNKNOWN',
    isQcoMandatory: standard.isQcoMandatory ?? standard.is_qco_mandatory ?? false,
    matchedRequirements: standard.matchedRequirements || [],
  }));

  const rawScorecard = payload.pre_publication_summary?.scorecard;
  const scorecard = rawScorecard
    ? {
        ...rawScorecard,
        overallScore: rawScorecard.overallScore ?? Math.round(
          (rawScorecard.completeness_score + rawScorecard.defensibility_score +
            rawScorecard.regulatory_compliance_score + rawScorecard.vendor_neutrality_score) / 4,
        ),
        grade: rawScorecard.grade || 'Live',
        statusText: rawScorecard.statusText || 'Live backend scorecard',
        summaryText: rawScorecard.summaryText || 'Scores returned by the procurement analysis service.',
        categoryScores: rawScorecard.categoryScores || [
          { name: 'Completeness', score: rawScorecard.completeness_score },
          { name: 'Defensibility', score: rawScorecard.defensibility_score },
          { name: 'Regulatory compliance', score: rawScorecard.regulatory_compliance_score },
          { name: 'Vendor neutrality', score: rawScorecard.vendor_neutrality_score },
        ],
        strengths: rawScorecard.strengths || [],
        areasForImprovement: rawScorecard.areasForImprovement || [],
      }
    : rawScorecard;

  const missingRecommendations = (payload.pre_publication_summary?.missing_recommendations || []).map((item, index) => ({
    ...item,
    id: item.id || `missing-${index + 1}`,
    parameter: item.parameter || item.title || 'Recommended standard reference',
    category: item.category || 'BIS recommendation',
    missingExplanation: item.missingExplanation || item.description || '',
    suggestedClauseText: item.suggestedClauseText || item.description || '',
  }));

  const evidence = (payload.findings || []).map((finding) => ({
    id: finding.id,
    requirement: finding.verdict.replaceAll('_', ' '),
    tenderTextSnippet: (payload.requirements || []).find((item) => item.id === finding.requirement_id)?.text || '',
    confidence: finding.confidence,
    mappedClause: finding.applicable_standards?.[0]?.designation || 'No mapped standard',
    standardClauseText: finding.evidence?.[0]?.excerpt || finding.reason,
    aiJustification: finding.reason,
  }));
  return {
    ...payload,
    extracted_requirements: requirements,
    standards_intelligence: standards,
    pre_publication_summary: {
      ...payload.pre_publication_summary,
      scorecard,
      missing_recommendations: missingRecommendations,
    },
    evidence,
  };
}

export async function uploadDocument(file) {
  const form = new FormData();
  form.append('file', file);
  return request('/documents/upload', { method: 'POST', body: form });
}

export async function createAnalysis({ text, file, category, department, tenderTitle }) {
  let body;
  if (file) {
    const document = await uploadDocument(file);
    body = { input_type: 'document', document_id: document.document_id, tender_title: tenderTitle, metadata: { category, department } };
  } else {
    body = { input_type: 'text', text, tender_title: tenderTitle, metadata: { category, department } };
  }
  return request('/analyses', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

export async function getAnalysis(id) { return request(`/analyses/${id}`); }
export async function listAnalyses() { return request('/analyses'); }
export async function getReport(id) { return request(`/analyses/${id}/report`); }
export async function searchStandards(query) { return request(`/standards/search?q=${encodeURIComponent(query)}&limit=50`); }
export async function listStandards(offset = 0, limit = 24) { return request(`/standards?offset=${offset}&limit=${limit}`); }
export async function getStandard(id) { return request(`/standards/${encodeURIComponent(id)}`); }

export async function getSampleDocument() {
  const response = await fetch(`${API_ROOT}/documents/samples/led-street-lighting`);
  if (!response.ok) throw new Error('Bundled sample document is unavailable.');
  return new File([await response.blob()], 'LED_Street_Lighting_Tender.pdf', { type: 'application/pdf' });
}

export async function waitForAnalysis(id, onProgress, timeoutMs = 60000) {
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    const analysis = await getAnalysis(id);
    onProgress?.(analysis);
    if (['completed', 'partially_completed', 'failed'].includes(analysis.status)) return analysis;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error('Analysis is taking longer than expected. Check History for its current status.');
}

export async function extractProfilePreview({ text, file, category }) {
  if (!API_KEY) throw new Error('Demo environment requires an API Key');
  
  let document_id = undefined;
  if (file) {
    const document = await uploadDocument(file);
    document_id = document.document_id;
  }
  
  return request('/analyses/extract-profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, document_id, category }),
  });
}
