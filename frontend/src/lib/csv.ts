/**
 * CSV export for the current Scatter Explorer dot set.
 *
 * Per CHUNK_7_DESIGN.md §2:
 *   - Columns: player_id, name, position, team, season, week, x_stat, x_value,
 *     y_stat, y_value, color_stat, color_value, size_stat, size_value
 *   - stat_id columns are repeated on every row (denormalized, makes the file
 *     self-documenting in Excel)
 *   - week column is empty when granularity is season or career
 *   - Numeric values formatted via each stat's format_str
 *   - Nulls as empty strings
 *   - Filename: <x>_vs_<y>_<positions>_<seasons>_<granularity>_<YYYYMMDD>.csv
 *
 * No backend round-trip; everything we need is already in QueryResponse.
 */

import type { QueryConfig, QueryResponse, Dot, StatMeta } from '@/types/api';
import { formatStat } from '@/lib/utils';

// ───────────────────────────────────────────────────────────────────────────
// Public entry point
// ───────────────────────────────────────────────────────────────────────────

export function exportDotsAsCSV(
  result: QueryResponse,
  config: QueryConfig,
): void {
  const csv = buildCSV(result, config);
  const filename = buildFilename(config, result.x_meta, result.y_meta);
  triggerDownload(csv, filename);
}

// ───────────────────────────────────────────────────────────────────────────
// CSV body
// ───────────────────────────────────────────────────────────────────────────

function buildCSV(result: QueryResponse, config: QueryConfig): string {
  const { dots, x_meta, y_meta, color_meta, size_meta } = result;

  const header = [
    'player_id', 'name', 'position', 'team', 'season', 'week',
    'x_stat', 'x_value',
    'y_stat', 'y_value',
    'color_stat', 'color_value',
    'size_stat', 'size_value',
  ];

  const xStatId = x_meta.stat_id;
  const yStatId = y_meta.stat_id;
  const colorStatId = color_meta?.stat_id ?? '';
  const sizeStatId = size_meta?.stat_id ?? '';

  // week column is the same value for every row (or empty)
  const weekValue =
    config.granularity === 'week' && config.week != null
      ? String(config.week)
      : '';

  const rows: string[] = [header.map(escapeCSV).join(',')];

  for (const d of dots) {
    rows.push(
      [
        d.player_id ?? '',
        d.name ?? '',
        d.pos ?? '',
        d.team ?? '',
        d.season == null ? '' : String(d.season),
        weekValue,
        xStatId,    formatValue(d.x, x_meta),
        yStatId,    formatValue(d.y, y_meta),
        colorStatId, formatValue(d.color, color_meta),
        sizeStatId,  formatValue(d.size, size_meta),
      ]
        .map(escapeCSV)
        .join(','),
    );
  }

  // UTF-8 BOM — without it, Excel mis-detects encoding for names with accents.
  return '\uFEFF' + rows.join('\r\n');
}

/**
 * Format a dot value for the CSV. Returns:
 *   - '' when value or meta is null/undefined
 *   - the value as-is (string-cast) when the stat is categorical
 *   - formatStat output for continuous numeric values
 */
function formatValue(
  value: Dot['x'] | Dot['color'] | Dot['size'],
  meta: StatMeta | null,
): string {
  if (value == null || meta == null) return '';
  if (meta.value_type === 'categorical') return String(value);
  if (typeof value === 'number') {
    return formatStat(value, meta.format_str);
  }
  // numeric stat with non-numeric value — unusual; pass through
  return String(value);
}

/**
 * Escape a single CSV cell per RFC 4180. Wrap in quotes if the field contains
 * comma, quote, CR, or LF; double inner quotes.
 */
function escapeCSV(field: string): string {
  if (field === '') return '';
  if (/[",\r\n]/.test(field)) {
    return `"${field.replace(/"/g, '""')}"`;
  }
  return field;
}

// ───────────────────────────────────────────────────────────────────────────
// Filename
// ───────────────────────────────────────────────────────────────────────────

export function buildFilename(
  config: QueryConfig,
  xMeta: StatMeta,
  yMeta: StatMeta,
): string {
  const parts: string[] = [
    xMeta.stat_id,
    'vs',
    yMeta.stat_id,
    positionsSegment(config.positions),
    seasonsSegment(config),
    granularitySegment(config),
    dateStamp(),
  ];
  return parts.join('_') + '.csv';
}

function positionsSegment(positions: string[]): string {
  if (positions.length === 0) return 'all';
  // Sanitize: stat positions should already be alphanumeric, but be defensive
  return positions.map(p => p.replace(/[^A-Za-z0-9]/g, '')).join('-');
}

function seasonsSegment(config: QueryConfig): string {
  const ss = config.seasons;
  if (ss.length === 0) return 'noseason';
  if (ss.length === 1) return String(ss[0]);
  // Min-max range — per design, hyphenate even when gaps exist. The CSV
  // contents are authoritative; the filename is just a hint.
  const lo = Math.min(...ss);
  const hi = Math.max(...ss);
  return `${lo}-${hi}`;
}

function granularitySegment(config: QueryConfig): string {
  if (config.granularity === 'week' && config.week != null) {
    return `W${config.week}`;
  }
  return config.granularity;
}

function dateStamp(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${yyyy}${mm}${dd}`;
}

// ───────────────────────────────────────────────────────────────────────────
// Download trigger
// ───────────────────────────────────────────────────────────────────────────

function triggerDownload(csvContent: string, filename: string): void {
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  // Some browsers require the anchor to be in the DOM
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  // Revoke after a tick so the click handler has consumed the URL
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
