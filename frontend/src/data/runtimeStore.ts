// Runtime store for REAL analyses fetched from the live backend.
//
// The rich mock records in mockData.ts stay as guaranteed-good SIH demo
// showcases (ids an-001/002/003). Any genuinely new submission is real: its
// adapted bundle is registered here, and the mockData getters read this store
// first (cache-first) so every tab lights up with real data automatically.
//
// No circular imports: this module imports only types + a type-only
// AdaptedAnalysis from the adapter (adapter imports only types; mockData
// imports this store, never the reverse).
import type {
  Analysis,
  EvidenceChainItem,
  MatchedRequirementItem,
  RegulatoryRequirement,
  SpecificationRequirement,
  Standard,
  StandardRelationship,
} from './types';
import type { AdaptedAnalysis } from '@/services/adapter';

export const SEEDED_ANALYSIS_IDS = new Set(['an-001', 'an-002', 'an-003', 'an-hindi', 'an-tamil']);

export function isSeededAnalysisId(id: string): boolean {
  return SEEDED_ANALYSIS_IDS.has(id);
}

interface RealBundle {
  analysis: Analysis;
  standards: Standard[];
  matchedRequirements: MatchedRequirementItem[];
  specRequirements: SpecificationRequirement[];
  regulatory: RegulatoryRequirement[];
  evidence: EvidenceChainItem[];
  relationships: StandardRelationship[];
}

const analysisStore = new Map<string, RealBundle>();
const standardStore = new Map<string, Standard>();

export function registerRealAnalysis(bundle: AdaptedAnalysis): void {
  const id = bundle.analysis.id;
  if (!id) return;
  analysisStore.set(id, {
    analysis: bundle.analysis,
    standards: bundle.standards,
    matchedRequirements: bundle.matchedRequirements,
    specRequirements: bundle.specRequirements,
    regulatory: bundle.regulatory,
    evidence: bundle.evidence,
    relationships: bundle.relationships,
  });
  for (const s of bundle.standards) standardStore.set(s.id, s);
}

// Register a single standard fetched on its own (e.g. Standards catalog / detail),
// so intra-app links resolve without re-fetching.
export function registerRealStandard(std: Standard): void {
  if (std?.id) standardStore.set(std.id, std);
}

export function hasRealAnalysis(id: string): boolean {
  return analysisStore.has(id);
}

export function getRealAnalysis(id: string): Analysis | undefined {
  return analysisStore.get(id)?.analysis;
}

export function getRealStandardById(id: string): Standard | undefined {
  return standardStore.get(id);
}

export function getRealMatchedRequirements(id: string): MatchedRequirementItem[] | undefined {
  return analysisStore.get(id)?.matchedRequirements;
}

export function getRealSpecRequirements(id: string): SpecificationRequirement[] | undefined {
  return analysisStore.get(id)?.specRequirements;
}

export function getRealRegulatory(id: string): RegulatoryRequirement[] | undefined {
  return analysisStore.get(id)?.regulatory;
}

export function getRealEvidence(id: string): EvidenceChainItem[] | undefined {
  return analysisStore.get(id)?.evidence;
}

export function getRealRelationships(id: string): StandardRelationship[] | undefined {
  return analysisStore.get(id)?.relationships;
}

export function listRealAnalyses(): Analysis[] {
  return Array.from(analysisStore.values()).map((b) => b.analysis);
}
