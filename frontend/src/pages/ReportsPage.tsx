import { useState } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { API_ROOT, API_KEY } from '@/services/api';
import {
  Award,
  Calendar,
  CheckCircle2,
  Clock,
  Download,
  Send,
  Eye,
  FileCheck2,
  FileSearch,
  FileText,
  Filter,
  Layers,
  ListChecks,
  Printer,
  Scale,
  ScrollText,
  Search,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  UserCheck,
  X,
} from 'lucide-react';
import { TopNav } from '@/components/TopNav';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Avatar } from '@/components/ui/Avatar';
import { useRouter } from '@/router';
import { reports, getAnalysisById } from '@/data/mockData';
import { listRealAnalyses } from '@/data/runtimeStore';
import { formatDate } from '@/utils/format';
import type { Report, ReportType } from '@/data/types';

const reportTypeConfig: Record<ReportType, { label: string; icon: typeof FileText; accent: string }> = {
  compliance: { label: 'Standards Intelligence Brief', icon: ShieldCheck, accent: 'text-teal-700 bg-teal-50 dark:bg-teal-950/60 dark:text-teal-300' },
  'gap-analysis': { label: 'Specification Quality Audit', icon: ListChecks, accent: 'text-amber-700 bg-amber-50 dark:bg-amber-950/60 dark:text-amber-300' },
  certification: { label: 'Regulatory & Certification Brief', icon: Award, accent: 'text-blue-700 bg-blue-50 dark:bg-blue-950/60 dark:text-blue-300' },
};

// Synthesize report entries for any real analyses registered this session.
// These are prepended so real submissions appear above the demo showcases.
function getRealReports(): Report[] {
  return listRealAnalyses().map((a) => ({
    id: `real-${a.id}`,
    analysisId: a.id,
    title: a.tenderTitle || a.id,
    type: 'compliance' as ReportType,
    generatedAt: a.createdAt || new Date().toISOString(),
    format: 'PDF' as const,
    pages: 0,
    status: 'ready' as const,
    author: 'StandIQ Intelligence Engine',
  }));
}

export function ReportsPage() {
  const { navigate } = useRouter();
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<ReportType | 'all'>('all');
  const [previewReport, setPreviewReport] = useState<Report | null>(null);
  const [isEmailing, setIsEmailing] = useState<string | null>(null);

  const handleEmailReport = async (reportId: string, analysisId: string) => {
    setIsEmailing(reportId);
    try {
      const res = await fetch(`${API_ROOT}/analyses/${analysisId}/report/email`, { method: 'POST', headers: { 'X-API-Key': API_KEY } });
      if (!res.ok) throw new Error('Failed to send email via n8n');
      alert('Report successfully dispatched for email delivery via n8n!');
    } catch (err) {
      alert('Failed to send email. Check backend logs.');
    } finally {
      setIsEmailing(null);
    }
  };

  const allReports = [...getRealReports(), ...reports];
  const filtered = allReports.filter((r) => {
    if (search && !r.title.toLowerCase().includes(search.toLowerCase())) return false;

    if (typeFilter !== 'all' && r.type !== typeFilter) return false;
    return true;
  });

  return (
    <div className="min-h-screen bg-ivory-50 text-ink-900 dark:bg-[#090D16] dark:text-slate-100">
      <TopNav variant="app" />

      <div className="container-app py-8">
        {/* Header */}
        <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-2xl font-bold tracking-tight text-ink-900 dark:text-white">Defensible Reports</h1>
              <span className="rounded bg-teal-50 px-2 py-0.5 text-[10px] font-semibold text-teal-800 border border-teal-200 font-mono dark:bg-teal-950/70 dark:text-teal-300 dark:border-teal-800">
                Audit Artifacts
              </span>
            </div>
            <p className="mt-1 text-sm text-ink-500 dark:text-slate-400">
              Structured procurement evaluation briefs with clause-level provenance, standards mapping, and officer review records.
            </p>
          </div>
        </div>

        {/* Toolbar */}
        <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-400 dark:text-slate-500" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search evaluation reports by title or ID…"
              className="input pl-9"
            />
            {search && (
              <button
                onClick={() => setSearch('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-600 dark:text-slate-500 dark:hover:text-slate-300"
              >
                <X size={15} />
              </button>
            )}
          </div>

          <div className="flex rounded-lg border border-ink-200 bg-white p-0.5 dark:border-slate-800 dark:bg-[#111827]">
            {(['all', 'compliance', 'gap-analysis', 'certification'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setTypeFilter(f)}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                  typeFilter === f
                    ? 'bg-ink-900 text-white dark:bg-teal-700'
                    : 'text-ink-500 hover:text-ink-700 dark:text-slate-400 dark:hover:text-slate-200'
                }`}
              >
                {f === 'all' ? 'All (3)' : reportTypeConfig[f].label.split(' ')[0]}
              </button>
            ))}
          </div>
        </div>

        {/* Reports grid */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {filtered.map((report, i) => {
            const analysis = getAnalysisById(report.analysisId);
            const typeConfig = reportTypeConfig[report.type];
            const Icon = typeConfig.icon;
            return (
              <motion.div
                key={report.id}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: i * 0.05 }}
              >
                <Card padding="lg" interactive className="flex h-full flex-col">
                  <div className="flex items-start justify-between gap-3">
                    <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${typeConfig.accent}`}>
                      <Icon size={18} />
                    </div>
                    <Badge variant="success">Audit Ready</Badge>
                  </div>

                  <div className="mt-4 flex-1">
                    <h3 className="text-sm font-semibold text-ink-900 dark:text-slate-100">{report.title}</h3>
                    {analysis && (
                      <button
                        onClick={() => navigate({ name: 'analysis', analysisId: analysis.id, tab: 'overview' })}
                        className="mt-1 text-xs text-teal-700 hover:underline dark:text-teal-400 block text-left"
                      >
                        Target: {analysis.title}
                      </button>
                    )}
                  </div>

                  <div className="mt-4 flex items-center justify-between border-t border-ink-100 pt-3 dark:border-slate-800">
                    <div className="flex items-center gap-2">
                      <Avatar initials={report.author.split(' ').map((n) => n[0]).join('')} size="sm" />
                      <div>
                        <p className="text-xs font-medium text-ink-700 dark:text-slate-300">{report.author}</p>
                        <p className="flex items-center gap-1 text-xs text-ink-400 dark:text-slate-500">
                          <Calendar size={11} />
                          {formatDate(report.generatedAt)}
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Badge variant="neutral">{report.format}</Badge>
                      <span className="text-xs text-ink-400 dark:text-slate-500">{report.pages}p</span>
                    </div>
                  </div>

                  <div className="mt-4 grid grid-cols-3 gap-2">
                    <Button
                      variant="secondary"
                      size="sm"
                      leftIcon={<Eye size={13} />}
                      onClick={() => setPreviewReport(report)}
                    >
                      View
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      leftIcon={<Download size={14} />}
                      onClick={() => window.open(`${API_ROOT}/analyses/${report.analysisId}/report/pdf`, '_blank')}
                    >
                      PDF
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={isEmailing === report.id}
                      leftIcon={<Send size={13} />}
                      onClick={() => handleEmailReport(report.id, report.analysisId)}
                    >
                      {isEmailing === report.id ? 'Sending...' : 'Email'}
                    </Button>
                  </div>
                </Card>
              </motion.div>
            );
          })}
        </div>

        {filtered.length === 0 && (
          <Card padding="lg" className="text-center">
            <Filter size={24} className="mx-auto mb-2 text-ink-400" />
            <p className="text-sm font-medium text-ink-900 dark:text-slate-100">No reports found</p>
            <p className="mt-1 text-sm text-ink-400 dark:text-slate-500">Try adjusting your search or filters.</p>
            <Button variant="secondary" onClick={() => { setSearch(''); setTypeFilter('all'); }} className="mt-4">
              Clear filters
            </Button>
          </Card>
        )}
      </div>

      {/* Document-Style Report Preview Modal */}
      <AnimatePresence>
        {previewReport && (
          <ReportPreviewModal report={previewReport} onClose={() => setPreviewReport(null)} />
        )}
      </AnimatePresence>
    </div>
  );
}

function ReportPreviewModal({ report, onClose }: { report: Report; onClose: () => void }) {
  const analysis = getAnalysisById(report.analysisId);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="absolute inset-0 bg-ink-900/50 backdrop-blur-sm transition-opacity dark:bg-black/70" />
      <motion.div
        initial={{ opacity: 0, scale: 0.96 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.96 }}
        transition={{ duration: 0.2 }}
        onClick={(e) => e.stopPropagation()}
        className="relative flex max-h-[90vh] w-full max-w-4xl flex-col rounded-xl border border-ink-200 bg-white shadow-pop overflow-hidden dark:border-slate-800 dark:bg-[#111827]"
      >
        {/* Document Action Topbar */}
        <div className="flex items-center justify-between border-b border-ink-200 bg-ivory-50/80 px-6 py-3 dark:border-slate-800 dark:bg-[#090D16]/80">
          <div className="flex items-center gap-2">
            <span className="rounded bg-teal-50 px-2 py-0.5 text-[10px] font-mono font-bold text-teal-800 border border-teal-200 dark:bg-teal-950 dark:text-teal-300 dark:border-teal-800">
              OFFICIAL INTELLIGENCE BRIEF
            </span>
            <span className="text-xs text-ink-500 font-mono dark:text-slate-400">
              Ref: {report.id.toUpperCase()} · SHA-256 Verified
            </span>
          </div>

          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<Printer size={13} />}
              onClick={() => window.print()}
            >
              Print
            </Button>
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<Download size={14} />}
              onClick={() => window.open(`${API_ROOT}/analyses/${report.analysisId}/report/pdf`, '_blank')}
            >
              Export PDF
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={isEmailing === report.id}
              leftIcon={<Send size={13} />}
              onClick={() => handleEmailReport(report.id, report.analysisId)}
            >
              {isEmailing === report.id ? 'Sending...' : 'Email to Officer'}
            </Button>
            <button
              onClick={onClose}
              className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-100 hover:text-ink-700 dark:text-slate-500 dark:hover:bg-slate-800 dark:hover:text-slate-300"
            >
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Document Scrollable Body */}
        <div className="overflow-y-auto p-6 sm:p-10 space-y-6 text-ink-900 dark:text-slate-100 font-sans">
          {/* Document Header Letterhead */}
          <div className="border-b-2 border-ink-900 pb-5 dark:border-slate-700">
            <div className="flex justify-between items-start">
              <div>
                <p className="text-[11px] font-mono font-semibold uppercase tracking-widest text-teal-800 dark:text-teal-400">
                  StandIQ Technical Procurement Intelligence Platform
                </p>
                <h1 className="text-xl font-bold tracking-tight text-ink-900 dark:text-white mt-1">
                  {report.title}
                </h1>
                <p className="text-xs text-ink-500 mt-1 font-mono dark:text-slate-400">
                  Analysis Scope: {analysis?.title || 'LED Street Lighting — NIT #MCD-2024-LT-09'}
                </p>
              </div>
              <div className="text-right font-mono text-xs text-ink-600 dark:text-slate-400">
                <p>Date: {formatDate(report.generatedAt)}</p>
                <p>Author: {report.author}</p>
                <p>Security: Commercial-in-Confidence</p>
              </div>
            </div>
          </div>

          {/* Section 1: Executive Summary & Procurement Profile */}
          <div>
            <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-ink-500 dark:text-slate-400 border-b border-ink-100 pb-1 mb-3 dark:border-slate-800">
              1. Procurement Context & Profile
            </h2>
            <div className="grid gap-3 sm:grid-cols-3 rounded-lg border border-ink-200 bg-ivory-50/50 p-3.5 text-xs dark:border-slate-800 dark:bg-[#161f30]/60">
              <div>
                <span className="text-[10px] uppercase font-mono text-ink-400 block font-semibold dark:text-slate-500">Product Scope</span>
                <span className="font-semibold text-ink-900 dark:text-white">Commercial LED Street Luminaire (90W–120W)</span>
              </div>
              <div>
                <span className="text-[10px] uppercase font-mono text-ink-400 block font-semibold dark:text-slate-500">Intended Application</span>
                <span className="font-semibold text-ink-900 dark:text-white">Municipal Arterial Roads & Expressways</span>
              </div>
              <div>
                <span className="text-[10px] uppercase font-mono text-ink-400 block font-semibold dark:text-slate-500">Operating Environment</span>
                <span className="font-semibold text-ink-900 dark:text-white">Outdoor / IP66 Ingress / 45°C Ambient</span>
              </div>
            </div>
          </div>

          {/* Section 2: Applicable Standards & Version Intelligence */}
          <div>
            <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-ink-500 dark:text-slate-400 border-b border-ink-100 pb-1 mb-3 dark:border-slate-800">
              2. Applicable Indian Standards & Version Chronology
            </h2>
            <div className="space-y-2 text-xs">
              <div className="rounded-lg border border-teal-200 bg-teal-50/30 p-3 dark:border-teal-900/60 dark:bg-teal-950/20">
                <div className="flex items-center justify-between font-mono font-semibold text-teal-950 dark:text-teal-300">
                  <span>IS 10322 (Part 5/Sec 3):2012 — Luminaires: Particular Requirements</span>
                  <span className="rounded bg-teal-100 px-1.5 py-0.5 text-[10px] font-bold text-teal-900 dark:bg-teal-900 dark:text-teal-200">
                    Primary Applicable Standard · 91% Applicability
                  </span>
                </div>
                <p className="mt-1 text-ink-700 dark:text-slate-300">
                  Current edition reaffirmed in 2022. Incorporates Amendment 1 & 2. Formally supersedes IS 2149:1970. Direct requirement match for housing, optical, and mechanical safety.
                </p>
              </div>

              <div className="grid gap-2 sm:grid-cols-2">
                <div className="rounded-lg border border-ink-200 p-2.5 bg-white dark:border-slate-800 dark:bg-[#161f30]/40">
                  <span className="font-mono font-bold text-ink-900 dark:text-white block">IS 15885 (Part 2/Sec 13):2012</span>
                  <span className="text-[11px] text-ink-500 dark:text-slate-400">LED Driver Safety · MeitY CRS Mandatory Schedule</span>
                </div>
                <div className="rounded-lg border border-ink-200 p-2.5 bg-white dark:border-slate-800 dark:bg-[#161f30]/40">
                  <span className="font-mono font-bold text-ink-900 dark:text-white block">IS 16107 (Part 2/Sec 1):2012</span>
                  <span className="text-[11px] text-ink-500 dark:text-slate-400">LED Luminaire Performance · Efficacy ≥ 135 lm/W</span>
                </div>
              </div>
            </div>
          </div>

          {/* Section 3: Specification Quality & Corrigenda */}
          <div>
            <h2 className="text-xs font-mono font-bold uppercase tracking-wider text-ink-500 dark:text-slate-400 border-b border-ink-100 pb-1 mb-3 dark:border-slate-800">
              3. Specification Quality & Actionable Findings
            </h2>
            <div className="space-y-2 text-xs">
              <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-3 dark:border-amber-900/60 dark:bg-amber-950/20">
                <div className="flex items-center gap-2 text-amber-900 dark:text-amber-300 font-semibold font-mono">
                  <ShieldAlert size={14} className="text-amber-700 shrink-0" />
                  <span>Mandatory Corrigendum: Remove citation of withdrawn IS 1944:1981 in NIT §4.2</span>
                </div>
                <p className="mt-1 text-ink-700 dark:text-slate-300 pl-6">
                  Tender NIT §4.2 cites withdrawn code. Corrigendum should update citation to IS 10322 (Part 5/Sec 3) read with National Lighting Code SP 72:2010.
                </p>
              </div>

              <div className="rounded-lg border border-ink-200 bg-white p-3 dark:border-slate-800 dark:bg-[#161f30]/40">
                <div className="flex items-center gap-2 text-ink-900 dark:text-white font-semibold font-mono">
                  <CheckCircle2 size={14} className="text-teal-700 shrink-0" />
                  <span>Mandate 10kV Driver Surge Protection in Technical Schedule §3.2.4</span>
                </div>
                <p className="mt-1 text-ink-600 dark:text-slate-400 pl-6">
                  Tender mentions surge protection qualitatively without defining the 10kV numerical threshold required by IS 16107 (Part 2/Sec 1) Cl 10.3.
                </p>
              </div>
            </div>
          </div>

          {/* Section 4: Audit Provenance & Sign-off */}
          <div className="border-t border-ink-200 pt-4 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-4 text-xs font-mono text-ink-500 dark:text-slate-400">
            <div>
              <p>Generated by StandIQ v2.4 Intelligence Engine</p>
              <p>Evidence records cryptographic signature: 9a8f…73b2</p>
            </div>
            <div className="rounded border border-ink-300 bg-ivory-50 p-2.5 dark:border-slate-700 dark:bg-[#161f30] text-center sm:text-right">
              <span className="block font-semibold text-ink-900 dark:text-white">Officer Review Status</span>
              <span className="text-success-700 font-bold dark:text-emerald-400">ACCEPTED & STAMPED FOR TENDER RELEASE</span>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}

