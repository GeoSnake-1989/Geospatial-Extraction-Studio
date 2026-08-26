export type BoundingBox = {
  west: number
  south: number
  east: number
  north: number
}

export type GeoJSONBoundary = {
  type: 'Polygon' | 'MultiPolygon'
  coordinates: unknown[]
}

export type PlaceResult = {
  name: string
  latitude: number
  longitude: number
  bounds: BoundingBox
  kind?: string
  boundary?: GeoJSONBoundary
  boundary_area_km2?: number
}

export type TerrainPreview = {
  grid: {
    rows: number
    columns: number
    values: number[][]
    valid_mask?: boolean[][]
    nodata_cells: number
  }
  statistics: {
    minimum: number
    maximum: number
    mean: number
    relief: number
  }
  spatial: {
    crs: string
    horizontal_units: string
    bounds: number[]
    source_width: number
    source_height: number
    preview_width: number
    preview_height: number
    nodata: number | null
    vertical_units: string
    vertical_datum: string
  }
}

export type DatasetResult = {
  id: string
  label: string
  provider: string
  product: string
  bounds: BoundingBox
  area_km2: number
  preview: TerrainPreview
  provenance: Record<string, string>
  files: {
    original: string
    processed: string
    source_evidence?: string
    documentation?: string
    documentation_download?: string
    package_download?: string
  }
}

export type OSMOutputFormat = 'openfilegdb' | 'geopackage'

export type OSMExportResult = {
  id: string
  label: string
  provider: 'OpenStreetMap'
  output_format?: OSMOutputFormat
  feature_type: string
  feature_subtype: string | null
  feature_count: number
  last_extraction_count?: number
  feature_classes: string[]
  extractions?: Array<{
    feature_type: string
    feature_subtype: string | null
    feature_count: number
    feature_classes: string[]
    bounds: BoundingBox
    area_km2: number
    selection_kind: 'bounding_box' | 'named_place_boundary'
    extracted_at?: string
  }>
  bounds: BoundingBox
  area_km2: number
  selection_kind?: 'bounding_box' | 'named_place_boundary'
  license: string
  files: {
    geodatabase: string
    attribution: string
    archive: string
    download: string
  }
}

export type OSMMapFeature = {
  type: 'Feature'
  geometry: {
    type: string
    coordinates: unknown
  }
  properties: Record<string, unknown>
}

export type OSMMapPreview = {
  type: 'FeatureCollection'
  features: OSMMapFeature[]
  feature_count: number
  displayed_feature_count: number
  truncated: boolean
  layers: Array<{
    name: string
    geometry_type: string
    feature_count: number
    displayed_feature_count: number
  }>
  crs: 'EPSG:4326'
}

export type NAIPSelectionMode = 'latest_complete' | 'latest_per_tile' | 'year'
export type NAIPBands = 'rgb' | 'rgbnir'

export type NAIPYearAvailability = {
  year: number
  coverage_percent: number
  fully_covered: boolean
  tile_count: number
  gsd_m: number
  acquisition_start: string | null
  acquisition_end: string | null
  estimated_pixels: number
}

export type NAIPAvailability = {
  provider: string
  catalog: string
  source_license_summary: string
  latest_complete_year: number | null
  latest_acquisition_date: string | null
  latest_per_tile_years: number[]
  latest_per_tile_coverage_percent: number
  latest_per_tile_gsd_m: number
  latest_per_tile_estimated_pixels: number
  max_output_pixels: number
  years: NAIPYearAvailability[]
}

export type NAIPImageryResult = {
  id: string
  label: string
  provider: string
  product: string
  attribution?: string
  license_note?: string
  source_license_summary?: string
  bounds: BoundingBox
  area_km2: number
  selection_mode: NAIPSelectionMode
  requested_year: number | null
  bands: NAIPBands
  years: number[]
  acquisition_start: string | null
  acquisition_end: string | null
  tile_count: number
  coverage_percent: number
  spatial: {
    crs: string
    width: number
    height: number
    pixel_count: number
    band_count: number
    resolution_m: number
    nodata: number | null
  }
  preview: { width: number; height: number }
  files: {
    manifest: string
    imagery: string
    preview: string
    documentation?: string
    manifest_download: string
    documentation_download?: string
    package_download?: string
    preview_download: string
  }
}

export type StorageSummary = {
  cache: { files: number; bytes: number }
  terrain: { files: number; bytes: number }
  imagery: { files: number; bytes: number }
  osm_exports: { files: number; bytes: number }
  generated_bytes: number
  total_bytes: number
}

export type Job<T> = {
  id: string
  state: 'queued' | 'downloading' | 'processing' | 'completed' | 'failed'
  progress: number
  message: string
  result?: T
  error?: string
}
