import type { BoundingBox, DatasetResult, GeoJSONBoundary, Job, OSMExportResult, OSMMapPreview, OSMOutputFormat, PlaceResult, StorageSummary } from './types'
import type { NAIPAvailability, NAIPBands, NAIPImageryResult, NAIPSelectionMode } from './types'

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(typeof body.detail === 'string' ? body.detail : 'The request could not be completed')
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string; service: string; providers: string[] }>('/api/health'),
  places: (query: string, scope: 'us' | 'world') =>
    request<PlaceResult[]>(`/api/places?q=${encodeURIComponent(query)}&scope=${scope}`),
  createElevationJob: (bounds: BoundingBox, previewSize: number, label: string) =>
    request<Job<DatasetResult>>('/api/elevation/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bounds, preview_size: previewSize, label }),
    }),
  elevationJob: (id: string) => request<Job<DatasetResult>>(`/api/elevation/jobs/${id}`),
  datasets: () => request<DatasetResult[]>('/api/datasets'),
  deleteDataset: (id: string) => request<{ message: string; id: string }>(`/api/datasets/${id}`, { method: 'DELETE' }),
  naipAvailability: (bounds: BoundingBox) => {
    const query = new URLSearchParams(Object.entries(bounds).map(([key, value]) => [key, String(value)]))
    return request<NAIPAvailability>(`/api/naip/availability?${query}`)
  },
  createNAIPJob: (
    bounds: BoundingBox,
    label: string,
    selectionMode: NAIPSelectionMode,
    year: number | null,
    bands: NAIPBands,
  ) => request<Job<NAIPImageryResult>>('/api/naip/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bounds,
      label,
      selection_mode: selectionMode,
      year: selectionMode === 'year' ? year : null,
      bands,
    }),
  }),
  naipJob: (id: string) => request<Job<NAIPImageryResult>>(`/api/naip/jobs/${id}`),
  naipImagery: () => request<NAIPImageryResult[]>('/api/naip/imagery'),
  deleteNAIPImagery: (id: string) => request<{ message: string; id: string; removed_files: boolean }>(`/api/naip/imagery/${id}`, { method: 'DELETE' }),
  createOSMJob: (
    bounds: BoundingBox,
    label: string,
    featureType: string,
    featureSubtype: string,
    boundary: GeoJSONBoundary | null,
    outputFormat: OSMOutputFormat,
    targetExportId: string | null,
  ) => request<Job<OSMExportResult>>('/api/osm/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bounds,
      label,
      feature_type: featureType,
      feature_subtype: featureSubtype || null,
      boundary,
      output_format: outputFormat,
      target_export_id: targetExportId,
    }),
  }),
  osmJob: (id: string) => request<Job<OSMExportResult>>(`/api/osm/jobs/${id}`),
  osmExports: () => request<OSMExportResult[]>('/api/osm/exports'),
  osmPreview: (id: string) => request<OSMMapPreview>(`/api/osm/exports/${id}/preview`),
  deleteOSMExport: (id: string) => request<{ message: string; id: string; removed_files: boolean }>(`/api/osm/exports/${id}`, { method: 'DELETE' }),
  storage: () => request<StorageSummary>('/api/storage'),
  clearCache: () => request<{ message: string; removed: { files: number; bytes: number }; storage: StorageSummary }>('/api/cache', { method: 'DELETE' }),
}
