import { FormEvent, useEffect, useMemo, useState } from 'react'
import {
  Activity,
  Archive,
  Box,
  ChevronDown,
  Database,
  Download,
  FileText,
  HardDrive,
  Images,
  Map,
  MapPin,
  Mountain,
  Search,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { api } from './api'
import { MapSelector } from './components/MapSelector'
import { TerrainScene, type ColorRamp } from './components/TerrainScene'
import { demoDataset } from './demo'
import type { BoundingBox, DatasetResult, GeoJSONBoundary, Job, OSMExportResult, OSMMapPreview, OSMOutputFormat, PlaceResult, StorageSummary } from './types'
import type { NAIPAvailability, NAIPBands, NAIPImageryResult, NAIPSelectionMode } from './types'

type Workflow = 'elevation' | 'osm' | 'naip'

const defaultBounds: BoundingBox = { west: -82.61, south: 27.91, east: -82.49, north: 28.01 }
const featureTypes = [
  'aerialway', 'aeroway', 'amenity', 'barrier', 'boundary', 'building', 'craft',
  'emergency', 'geological', 'highway', 'historic', 'landuse', 'leisure', 'man_made',
  'military', 'natural', 'office', 'place', 'power', 'public_transport', 'railway',
  'route', 'shop', 'sport', 'telecom', 'tourism', 'waterway',
]
const subtypeOptions: Record<string, string[]> = {
  aerialway: ['cable_car', 'gondola', 'chair_lift', 'drag_lift', 'goods'],
  aeroway: ['aerodrome', 'runway', 'taxiway', 'helipad', 'apron'],
  amenity: ['school', 'hospital', 'restaurant', 'cafe', 'bank', 'parking', 'place_of_worship', 'fuel', 'fire_station', 'police', 'library', 'bar', 'fast_food', 'pharmacy'],
  barrier: ['fence', 'wall', 'gate', 'bollard', 'hedge', 'kerb'],
  boundary: ['administrative', 'protected_area', 'national_park', 'postal_code'],
  building: ['yes', 'residential', 'commercial', 'industrial', 'retail', 'school', 'church'],
  craft: ['carpenter', 'electrician', 'plumber', 'brewery', 'winery', 'tailor'],
  emergency: ['fire_hydrant', 'phone', 'ambulance_station', 'defibrillator'],
  geological: ['outcrop', 'moraine', 'palaeontological_site'],
  highway: ['motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'residential', 'service', 'unclassified', 'footway', 'cycleway', 'path', 'bus_stop'],
  historic: ['building', 'memorial', 'monument', 'archaeological_site', 'castle'],
  landuse: ['residential', 'commercial', 'industrial', 'retail', 'forest', 'grass', 'farmland'],
  leisure: ['park', 'pitch', 'sports_centre', 'playground', 'garden', 'marina'],
  man_made: ['tower', 'mast', 'pier', 'bridge', 'water_tower', 'storage_tank'],
  military: ['base', 'barracks', 'checkpoint', 'danger_area'],
  natural: ['water', 'wood', 'wetland', 'beach', 'scrub', 'tree', 'coastline'],
  office: ['government', 'company', 'lawyer', 'estate_agent', 'insurance'],
  place: ['city', 'town', 'village', 'hamlet', 'suburb', 'neighbourhood'],
  power: ['tower', 'pole', 'line', 'minor_line', 'substation', 'generator', 'plant'],
  public_transport: ['platform', 'station', 'stop_position', 'stop_area'],
  railway: ['rail', 'tram', 'subway', 'station', 'halt', 'level_crossing'],
  route: ['bus', 'road', 'bicycle', 'hiking', 'ferry', 'train', 'tram'],
  shop: ['supermarket', 'convenience', 'clothes', 'mall', 'bakery', 'car', 'hardware'],
  sport: ['soccer', 'baseball', 'basketball', 'tennis', 'swimming', 'golf'],
  telecom: ['exchange', 'mast', 'data_center', 'antenna'],
  tourism: ['hotel', 'motel', 'attraction', 'museum', 'viewpoint', 'camp_site'],
  waterway: ['river', 'stream', 'canal', 'drain', 'ditch', 'dock'],
}

function areaKm2(bounds: BoundingBox) {
  const center = ((bounds.south + bounds.north) / 2) * (Math.PI / 180)
  return Math.abs((bounds.east - bounds.west) * 111.32 * Math.cos(center) * (bounds.north - bounds.south) * 110.574)
}

function Stat({ label, value, suffix = '' }: { label: string; value: string | number; suffix?: string }) {
  return <div className="stat"><span>{label}</span><strong>{value}{suffix}</strong></div>
}

function isBusy<T>(job: Job<T> | null) {
  return Boolean(job && !['completed', 'failed'].includes(job.state))
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

const osmOutputFormatLabels: Record<OSMOutputFormat, string> = {
  openfilegdb: 'OpenFileGDB',
  geopackage: 'GeoPackage',
}

function osmOutputFormatFor(item: OSMExportResult): OSMOutputFormat {
  if (item.output_format) return item.output_format
  return item.files.geodatabase.toLowerCase().endsWith('.gpkg') ? 'geopackage' : 'openfilegdb'
}

export default function App() {
  const [workflow, setWorkflow] = useState<Workflow>('elevation')
  const [bounds, setBounds] = useState<BoundingBox>(defaultBounds)
  const [boundary, setBoundary] = useState<GeoJSONBoundary | null>(null)
  const [boundaryArea, setBoundaryArea] = useState<number | null>(null)
  const [query, setQuery] = useState('')
  const [places, setPlaces] = useState<PlaceResult[]>([])
  const [searching, setSearching] = useState(false)
  const [label, setLabel] = useState('Tampa Bay study area')
  const [previewSize, setPreviewSize] = useState(96)
  const [naipSelectionMode, setNAIPSelectionMode] = useState<NAIPSelectionMode>('latest_complete')
  const [naipYear, setNAIPYear] = useState<number | null>(null)
  const [naipBands, setNAIPBands] = useState<NAIPBands>('rgb')
  const [naipAvailability, setNAIPAvailability] = useState<NAIPAvailability | null>(null)
  const [naipAvailabilityLoading, setNAIPAvailabilityLoading] = useState(false)
  const [naipAvailabilityError, setNAIPAvailabilityError] = useState('')
  const [featureType, setFeatureType] = useState('building')
  const [featureSubtype, setFeatureSubtype] = useState('')
  const [outputFormat, setOutputFormat] = useState<OSMOutputFormat>('openfilegdb')
  const [targetExportId, setTargetExportId] = useState('')
  const [active, setActive] = useState<DatasetResult>(demoDataset)
  const [activeNAIP, setActiveNAIP] = useState<NAIPImageryResult | null>(null)
  const [activeOSM, setActiveOSM] = useState<OSMExportResult | null>(null)
  const [osmPreview, setOSMPreview] = useState<OSMMapPreview | null>(null)
  const [osmPreviewLoading, setOSMPreviewLoading] = useState(false)
  const [osmPreviewError, setOSMPreviewError] = useState('')
  const [recent, setRecent] = useState<DatasetResult[]>([])
  const [recentNAIP, setRecentNAIP] = useState<NAIPImageryResult[]>([])
  const [recentOSM, setRecentOSM] = useState<OSMExportResult[]>([])
  const [elevationJob, setElevationJob] = useState<Job<DatasetResult> | null>(null)
  const [naipJob, setNAIPJob] = useState<Job<NAIPImageryResult> | null>(null)
  const [osmJob, setOSMJob] = useState<Job<OSMExportResult> | null>(null)
  const [error, setError] = useState('')
  const [backendOnline, setBackendOnline] = useState(false)
  const [storage, setStorage] = useState<StorageSummary | null>(null)
  const [storageOpen, setStorageOpen] = useState(false)
  const [storageBusy, setStorageBusy] = useState(false)
  const [storageMessage, setStorageMessage] = useState('')
  const [exaggeration, setExaggeration] = useState(1)
  const [wireframe, setWireframe] = useState(false)
  const [showSeaLevel, setShowSeaLevel] = useState(true)
  const [colorRamp, setColorRamp] = useState<ColorRamp>('topographic')
  const selectedArea = useMemo(() => boundaryArea ?? areaKm2(bounds), [boundaryArea, bounds])
  const currentJob = workflow === 'elevation' ? elevationJob : workflow === 'naip' ? naipJob : osmJob

  useEffect(() => {
    api.health().then(() => setBackendOnline(true)).catch(() => setBackendOnline(false))
    api.datasets().then(setRecent).catch(() => undefined)
    api.naipImagery().then((items) => {
      setRecentNAIP(items)
      if (items.length) setActiveNAIP(items[0])
    }).catch(() => undefined)
    api.osmExports().then((items) => {
      setRecentOSM(items)
      if (items.length) setActiveOSM(items[0])
    }).catch(() => undefined)
    api.storage().then(setStorage).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!elevationJob || ['completed', 'failed'].includes(elevationJob.state)) return
    const timer = window.setTimeout(async () => {
      try {
        const update = await api.elevationJob(elevationJob.id)
        setElevationJob(update)
        if (update.state === 'completed' && update.result) {
          setActive(update.result)
          setRecent((items) => [update.result!, ...items.filter((item) => item.id !== update.result!.id)])
          api.storage().then(setStorage).catch(() => undefined)
        }
        if (update.state === 'failed') setError(update.error || 'The elevation extraction failed.')
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Could not check extraction progress')
      }
    }, 900)
    return () => window.clearTimeout(timer)
  }, [elevationJob])

  useEffect(() => {
    if (!naipJob || ['completed', 'failed'].includes(naipJob.state)) return
    const timer = window.setTimeout(async () => {
      try {
        const update = await api.naipJob(naipJob.id)
        setNAIPJob(update)
        if (update.state === 'completed' && update.result) {
          setActiveNAIP(update.result)
          setRecentNAIP((items) => [update.result!, ...items.filter((item) => item.id !== update.result!.id)])
          api.storage().then(setStorage).catch(() => undefined)
        }
        if (update.state === 'failed') setError(update.error || 'The NAIP extraction failed.')
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Could not check NAIP extraction progress')
      }
    }, 900)
    return () => window.clearTimeout(timer)
  }, [naipJob])

  useEffect(() => {
    if (!osmJob || ['completed', 'failed'].includes(osmJob.state)) return
    const timer = window.setTimeout(async () => {
      try {
        const update = await api.osmJob(osmJob.id)
        setOSMJob(update)
        if (update.state === 'completed' && update.result) {
          setActiveOSM(update.result)
          setRecentOSM((items) => [update.result!, ...items.filter((item) => item.id !== update.result!.id)])
          api.storage().then(setStorage).catch(() => undefined)
        }
        if (update.state === 'failed') setError(update.error || 'The OSM extraction failed.')
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Could not check extraction progress')
      }
    }, 900)
    return () => window.clearTimeout(timer)
  }, [osmJob])

  useEffect(() => {
    if (workflow !== 'osm' || !activeOSM) {
      setOSMPreview(null)
      setOSMPreviewLoading(false)
      setOSMPreviewError('')
      return
    }
    let cancelled = false
    setOSMPreview(null)
    setOSMPreviewLoading(true)
    setOSMPreviewError('')
    api.osmPreview(activeOSM.id).then((preview) => {
      if (!cancelled) setOSMPreview(preview)
    }).catch((reason) => {
      if (!cancelled) setOSMPreviewError(reason instanceof Error ? reason.message : 'Could not load extracted features')
    }).finally(() => {
      if (!cancelled) setOSMPreviewLoading(false)
    })
    return () => { cancelled = true }
  }, [workflow, activeOSM?.id, activeOSM?.feature_count])

  useEffect(() => {
    if (workflow !== 'naip') return
    if (areaKm2(bounds) > 500) {
      setNAIPAvailability(null)
      setNAIPAvailabilityLoading(false)
      setNAIPAvailabilityError('Select an area smaller than 500 km? to check NAIP coverage.')
      return
    }
    let cancelled = false
    setNAIPAvailabilityLoading(true)
    setNAIPAvailabilityError('')
    const timer = window.setTimeout(() => {
      api.naipAvailability(bounds).then((availability) => {
        if (cancelled) return
        setNAIPAvailability(availability)
        setNAIPYear((current) => availability.years.some((item) => item.year === current)
          ? current
          : availability.latest_complete_year || availability.years[0]?.year || null)
      }).catch((reason) => {
        if (!cancelled) {
          setNAIPAvailability(null)
          setNAIPAvailabilityError(reason instanceof Error ? reason.message : 'Could not check NAIP availability')
        }
      }).finally(() => {
        if (!cancelled) setNAIPAvailabilityLoading(false)
      })
    }, 500)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [workflow, bounds.east, bounds.north, bounds.south, bounds.west])

  const switchWorkflow = (next: Workflow) => {
    setWorkflow(next)
    if (next !== 'osm') {
      setBoundary(null)
      setBoundaryArea(null)
    }
    setPlaces([])
    setError('')
  }

  const searchPlaces = async (event: FormEvent) => {
    event.preventDefault()
    if (query.trim().length < 2) return
    setSearching(true)
    setError('')
    try {
      setPlaces(await api.places(query.trim(), workflow === 'osm' ? 'world' : 'us'))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Place search failed')
    } finally {
      setSearching(false)
    }
  }

  const selectPlace = (place: PlaceResult) => {
    setBounds({
      west: Number(place.bounds.west.toFixed(6)), south: Number(place.bounds.south.toFixed(6)),
      east: Number(place.bounds.east.toFixed(6)), north: Number(place.bounds.north.toFixed(6)),
    })
    const nextBoundary = workflow === 'osm' ? place.boundary || null : null
    setBoundary(nextBoundary)
    setBoundaryArea(nextBoundary ? place.boundary_area_km2 || null : null)
    setLabel(place.name.split(',').slice(0, 2).join(','))
    setPlaces([])
    setQuery(place.name.split(',')[0])
  }

  const selectTargetExport = (exportId: string) => {
    setTargetExportId(exportId)
    const target = recentOSM.find((item) => item.id === exportId)
    if (target) {
      setActiveOSM(target)
      setOutputFormat(osmOutputFormatFor(target))
      setLabel(target.label)
    }
  }

  const selectedNAIPYear = naipAvailability?.years.find((item) => item.year === (
    naipSelectionMode === 'latest_complete' ? naipAvailability.latest_complete_year : naipYear
  ))
  const naipEstimatedPixels = naipSelectionMode === 'latest_per_tile'
    ? naipAvailability?.latest_per_tile_estimated_pixels || 0
    : selectedNAIPYear?.estimated_pixels || 0
  const naipSizeTooLarge = Boolean(
    naipAvailability && naipEstimatedPixels > naipAvailability.max_output_pixels,
  )

  const extract = async () => {
    setError('')
    if (workflow === 'naip' && selectedArea > 500) return setError('Select an area smaller than 500 km².')
    if (workflow === 'naip' && (naipAvailabilityLoading || !naipAvailability)) {
      return setError(naipAvailabilityError || 'Wait for the NAIP coverage check to finish.')
    }
    if (workflow === 'naip' && naipSelectionMode === 'latest_complete' && !naipAvailability?.latest_complete_year) {
      return setError('No single published NAIP year completely covers this area.')
    }
    if (workflow === 'naip' && naipSelectionMode === 'year' && !naipYear) {
      return setError('Choose a NAIP acquisition year.')
    }
    if (workflow === 'naip' && naipSizeTooLarge) {
      return setError(`Reduce the area below the ${(naipAvailability?.max_output_pixels || 0).toLocaleString()}-pixel safety limit.`)
    }
    if (workflow === 'elevation' && selectedArea > 2500) return setError('Select an area smaller than 2,500 km².')
    if (workflow === 'osm' && !boundary && selectedArea > 2500) return setError('Draw a rectangle smaller than 2,500 km², or select a named place boundary.')
    if (workflow === 'osm' && boundary && selectedArea > 10000) return setError('Select a named place boundary smaller than 10,000 km².')
    try {
      if (workflow === 'elevation') {
        setElevationJob(await api.createElevationJob(bounds, previewSize, label || 'Selected area'))
      } else if (workflow === 'naip') {
        setNAIPJob(await api.createNAIPJob(
          bounds,
          label || 'Selected area',
          naipSelectionMode,
          naipYear,
          naipBands,
        ))
      } else {
        setOSMJob(await api.createOSMJob(
          bounds,
          label || 'Selected area',
          featureType,
          featureSubtype,
          boundary,
          outputFormat,
          targetExportId || null,
        ))
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Could not start the extraction')
    }
  }

  const updateEdge = (edge: keyof BoundingBox, value: string) => {
    const number = Number(value)
    if (Number.isFinite(number)) {
      setBoundary(null)
      setBoundaryArea(null)
      setBounds((current) => ({ ...current, [edge]: number }))
    }
  }

  const clearBoundary = () => {
    setBoundary(null)
    setBoundaryArea(null)
  }

  const clearRequestCache = async () => {
    setStorageBusy(true)
    setStorageMessage('')
    try {
      const result = await api.clearCache()
      setStorage(result.storage)
      setStorageMessage(`${formatBytes(result.removed.bytes)} of reusable cache removed.`)
    } catch (reason) {
      setStorageMessage(reason instanceof Error ? reason.message : 'Could not clear the cache.')
    } finally {
      setStorageBusy(false)
    }
  }

  const removeDataset = async (item: DatasetResult) => {
    if (!window.confirm(`Permanently delete the saved terrain files for “${item.label}”?`)) return
    setStorageBusy(true)
    setStorageMessage('')
    try {
      await api.deleteDataset(item.id)
      const remaining = recent.filter((dataset) => dataset.id !== item.id)
      setRecent(remaining)
      if (active.id === item.id) setActive(remaining[0] || demoDataset)
      setStorage(await api.storage())
      setStorageMessage(`Deleted ${item.label}.`)
    } catch (reason) {
      setStorageMessage(reason instanceof Error ? reason.message : 'Could not delete the terrain dataset.')
    } finally {
      setStorageBusy(false)
    }
  }

  const removeNAIPImagery = async (item: NAIPImageryResult) => {
    if (!window.confirm(`Permanently delete the saved NAIP imagery for “${item.label}”?`)) return
    setStorageBusy(true)
    setStorageMessage('')
    try {
      const result = await api.deleteNAIPImagery(item.id)
      const remaining = recentNAIP.filter((imagery) => imagery.id !== item.id)
      setRecentNAIP(remaining)
      if (activeNAIP?.id === item.id) setActiveNAIP(remaining[0] || null)
      setStorage(await api.storage())
      setStorageMessage(`${result.message}.`)
    } catch (reason) {
      setStorageMessage(reason instanceof Error ? reason.message : 'Could not delete the NAIP imagery.')
    } finally {
      setStorageBusy(false)
    }
  }
  const removeOSMExport = async (item: OSMExportResult) => {
    if (!window.confirm(`Permanently delete the OSM dataset and ZIP for “${item.label}”?`)) return
    setStorageBusy(true)
    setStorageMessage('')
    try {
      const result = await api.deleteOSMExport(item.id)
      const remaining = recentOSM.filter((osmExport) => osmExport.id !== item.id)
      setRecentOSM(remaining)
      if (activeOSM?.id === item.id) setActiveOSM(remaining[0] || null)
      if (targetExportId === item.id) setTargetExportId('')
      setStorage(await api.storage())
      setStorageMessage(`${result.message}.`)
    } catch (reason) {
      setStorageMessage(reason instanceof Error ? reason.message : 'Could not delete the OSM export.')
    } finally {
      setStorageBusy(false)
    }
  }

  const stats = active.preview.statistics
  const busy = workflow === 'elevation' ? isBusy(elevationJob) : workflow === 'naip' ? isBusy(naipJob) : isBusy(osmJob)
  const availableSubtypes = subtypeOptions[featureType] || []
  const targetOSM = recentOSM.find((item) => item.id === targetExportId)
  const activeOSMFormat = activeOSM ? osmOutputFormatFor(activeOSM) : outputFormat

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark">
          <img src="/geospatial-extraction-studio-logo-green.png" alt="" aria-hidden="true" />
        </div>
        <div className="brand-copy"><strong>Geospatial Extraction Studio</strong><span>Local geospatial workflows</span></div>
        <div className="topbar-rule" />
        <div className={`service-status ${backendOnline ? 'online' : ''}`}><span className="status-dot" />{backendOnline ? 'Local service ready' : 'Start local service'}</div>
        <a className="legal-chip" href="/api/legal/third-party-notices" target="_blank" rel="noreferrer"><FileText size={14} /> Legal notices</a>
        <button className="storage-chip" onClick={() => setStorageOpen(true)}><HardDrive size={14} /> Storage {storage ? formatBytes(storage.total_bytes) : '—'}</button>
        <div className="source-chip"><Database size={14} /> {workflow === 'elevation' ? active.provider : workflow === 'naip' ? 'USDA NAIP / FSA' : 'OpenStreetMap'}</div>
      </header>

      {storageOpen && <div className="storage-backdrop" onClick={() => setStorageOpen(false)}>
        <section className="storage-panel" role="dialog" aria-modal="true" aria-label="Geospatial Extraction Studio storage" onClick={(event) => event.stopPropagation()}>
          <div className="storage-header"><div><span>Local storage</span><strong>Manage application files</strong></div><button aria-label="Close storage" onClick={() => setStorageOpen(false)}><X size={18} /></button></div>
          <div className="storage-totals">
            <div><span>Reusable cache</span><strong>{formatBytes(storage?.cache.bytes || 0)}</strong></div>
            <div><span>Terrain files</span><strong>{formatBytes(storage?.terrain.bytes || 0)}</strong></div>
            <div><span>NAIP imagery</span><strong>{formatBytes(storage?.imagery.bytes || 0)}</strong></div>
            <div><span>OSM exports</span><strong>{formatBytes(storage?.osm_exports.bytes || 0)}</strong></div>
          </div>
          <div className="storage-cache-row"><div><strong>OSM request cache</strong><span>Safe to clear. Completed terrain, NAIP imagery, and OSM datasets are preserved.</span></div><button disabled={storageBusy || !storage?.cache.bytes} onClick={clearRequestCache}><Trash2 size={14} /> Clear cache</button></div>
          <div className="storage-list"><div className="storage-list-title"><span>Saved NAIP imagery</span><b>{recentNAIP.length}</b></div>
            {recentNAIP.length ? recentNAIP.map((item) => <div className="storage-item" key={item.id}><div><strong>{item.label}</strong><span>{item.years.join(' / ')} · {item.spatial.resolution_m} m · {item.spatial.band_count} bands</span></div><button disabled={storageBusy} aria-label={`Delete ${item.label} NAIP imagery`} onClick={() => removeNAIPImagery(item)}><Trash2 size={14} /></button></div>) : <p className="storage-empty">No saved NAIP imagery.</p>}
          </div>          <div className="storage-list"><div className="storage-list-title"><span>Saved OSM datasets</span><b>{recentOSM.length}</b></div>
            {recentOSM.length ? recentOSM.map((item) => <div className="storage-item" key={item.id}><div><strong>{item.label}</strong><span>{osmOutputFormatLabels[osmOutputFormatFor(item)]} · {item.feature_classes.length} layer{item.feature_classes.length === 1 ? '' : 's'} · {item.feature_count.toLocaleString()} features</span></div><button disabled={storageBusy} aria-label={`Delete ${item.label} OSM export`} onClick={() => removeOSMExport(item)}><Trash2 size={14} /></button></div>) : <p className="storage-empty">No saved OSM datasets.</p>}
          </div>
          <div className="storage-list"><div className="storage-list-title"><span>Saved terrain datasets</span><b>{recent.length}</b></div>
            {recent.length ? recent.map((item) => <div className="storage-item" key={item.id}><div><strong>{item.label}</strong><span>{item.product}</span></div><button disabled={storageBusy} aria-label={`Delete ${item.label} terrain dataset`} onClick={() => removeDataset(item)}><Trash2 size={14} /></button></div>) : <p className="storage-empty">No saved terrain datasets.</p>}
          </div>
          {storageMessage && <p className="storage-message">{storageMessage}</p>}
        </section>
      </div>}

      <main className="workspace">
        <aside className="control-panel">
          <div className="control-panel-scroll">
          <div className="workflow-tabs" role="tablist" aria-label="Extraction workflow">
            <button className={workflow === 'elevation' ? 'active' : ''} onClick={() => switchWorkflow('elevation')}><Mountain size={15} />Elevation</button>
            <button className={workflow === 'naip' ? 'active' : ''} onClick={() => switchWorkflow('naip')}><Images size={15} />NAIP imagery</button>
            <button className={workflow === 'osm' ? 'active' : ''} onClick={() => switchWorkflow('osm')}><Archive size={15} />OSM features</button>
          </div>
          <div className="eyebrow"><Sparkles size={14} /> New {workflow === 'elevation' ? 'terrain' : workflow === 'naip' ? 'imagery' : 'feature'} extract</div>
          <h1>{workflow === 'elevation' ? <>Turn a place into<br />a terrain surface.</> : workflow === 'naip' ? <>Download the newest<br />aerial imagery.</> : <>Turn an area into<br />GIS feature classes.</>}</h1>
          <p className="lede">{workflow === 'elevation' ? 'Search a U.S. location or draw a rectangle. The source GeoTIFF is preserved and a lightweight 3D preview is built.' : workflow === 'naip' ? 'Choose a U.S. location and receive the newest complete NAIP coverage, or fill each part from its newest published tile.' : 'Search anywhere or draw a rectangle, choose an OSM tag and output format, and receive a zipped GIS dataset with its required attribution notice.'}</p>

          <section className="panel-section search-section">
            <div className="section-label"><span>01</span> Find a location <em>{workflow === 'osm' ? 'Worldwide' : 'U.S.'}</em></div>
            <form className="search-box" onSubmit={searchPlaces}>
              <Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={workflow === 'osm' ? 'City, landmark, or address worldwide' : 'U.S. city, landmark, or address'} />
              <button type="submit" aria-label="Search">{searching ? <Activity className="spin" size={16} /> : <span>Go</span>}</button>
            </form>
            {places.length > 0 && <div className="search-results">{places.map((place) => <button key={`${place.latitude}-${place.longitude}`} onClick={() => selectPlace(place)}><MapPin size={15} /><span>{place.name}</span></button>)}</div>}
          </section>

          <section className="panel-section">
            <div className="section-label"><span>02</span> Define the area <em>{boundary ? 'Named place boundary' : 'Draw on map'}</em></div>
            <div className="coordinate-grid">{(['west', 'north', 'east', 'south'] as Array<keyof BoundingBox>).map((edge) => <label key={edge}><span>{edge}</span><input type="number" step="0.000001" value={bounds[edge]} onChange={(event) => updateEdge(edge, event.target.value)} /></label>)}</div>
            <div className="area-readout"><Map size={15} /><span>{boundary ? 'Boundary footprint' : 'Selected footprint'}</span><strong>{selectedArea.toFixed(1)} km²</strong></div>
          </section>

          <section className="panel-section">
            <div className="section-label"><span>03</span> Extraction settings</div>
            {workflow === 'osm' && (
              <>
              <label className="field-label">Output format
                <div className="select-wrap"><select value={outputFormat} disabled={Boolean(targetOSM)} onChange={(event) => setOutputFormat(event.target.value as OSMOutputFormat)}>
                  <option value="openfilegdb">OpenFileGDB (.gdb)</option>
                  <option value="geopackage">GeoPackage (.gpkg)</option>
                </select><ChevronDown size={16} /></div>
              </label>
              <label className="field-label">Output dataset
                <div className="select-wrap"><select value={targetExportId} onChange={(event) => selectTargetExport(event.target.value)}>
                  <option value="">Create a new {osmOutputFormatLabels[outputFormat]} dataset</option>
                  {recentOSM.map((item) => <option key={item.id} value={item.id}>Add to {item.label} · {osmOutputFormatLabels[osmOutputFormatFor(item)]} · {item.feature_classes.length} layer{item.feature_classes.length === 1 ? '' : 's'}</option>)}
                </select><ChevronDown size={16} /></div>
              </label>
              </>
            )}
            <label className="field-label">Dataset label<input value={label} disabled={workflow === 'osm' && Boolean(targetOSM)} onChange={(event) => setLabel(event.target.value)} /></label>
            {workflow === 'elevation' ? (
              <>
                <label className="field-label">Elevation source<input value="USGS 3DEP · seamless" disabled /><span className="field-hint">The USGS 3DEP seamless dynamic service is the only elevation source.</span></label>
                <label className="field-label">3D preview detail<div className="select-wrap"><select value={previewSize} onChange={(event) => setPreviewSize(Number(event.target.value))}><option value={64}>Compact · 64 × 64</option><option value={96}>Balanced · 96 × 96</option><option value={128}>Detailed · 128 × 128</option></select><ChevronDown size={16} /></div><span className="field-hint">The downloadable source uses an adaptive ~10 m grid; this setting only controls viewer performance.</span></label>
              </>
            ) : workflow === 'naip' ? (
              <>
                <label className="field-label">Imagery source<input value="USDA NAIP · Planetary Computer STAC" disabled /><span className="field-hint">Availability is checked automatically for the current rectangle.</span></label>
                <label className="field-label">Imagery date
                  <div className="select-wrap"><select value={naipSelectionMode === 'year' ? `year:${naipYear || ''}` : naipSelectionMode} disabled={naipAvailabilityLoading || !naipAvailability} onChange={(event) => {
                    const value = event.target.value
                    if (value.startsWith('year:')) {
                      setNAIPSelectionMode('year')
                      setNAIPYear(Number(value.slice(5)))
                    } else {
                      setNAIPSelectionMode(value as NAIPSelectionMode)
                    }
                  }}>
                    <option value="latest_complete" disabled={!naipAvailability?.latest_complete_year}>Latest complete coverage{naipAvailability?.latest_complete_year ? ` · ${naipAvailability.latest_complete_year}` : ''}</option>
                    <option value="latest_per_tile">Newest imagery per tile{naipAvailability?.latest_per_tile_years.length ? ` · ${naipAvailability.latest_per_tile_years.join(' / ')}` : ''}</option>
                    {naipAvailability?.years.filter((item) => item.fully_covered).map((item) => <option key={item.year} value={`year:${item.year}`}>{item.year} complete coverage · {item.gsd_m} m</option>)}
                  </select><ChevronDown size={16} /></div>
                  <span className="field-hint">Complete coverage uses one consistent year. Per-tile mode may contain visible date seams.</span>
                </label>
                <label className="field-label">Bands<div className="select-wrap"><select value={naipBands} onChange={(event) => setNAIPBands(event.target.value as NAIPBands)}><option value="rgb">Natural color · RGB</option><option value="rgbnir">Four band · RGB + near infrared</option></select><ChevronDown size={16} /></div></label>
                <div className={`naip-availability ${naipSizeTooLarge || naipAvailabilityError ? 'error' : ''}`}>
                  {naipAvailabilityLoading ? <><Activity className="spin" size={14} /><span>Checking published NAIP coverage…</span></> : naipAvailabilityError ? <span>{naipAvailabilityError}</span> : naipAvailability ? <><span>{selectedNAIPYear?.coverage_percent ?? naipAvailability.latest_per_tile_coverage_percent}% coverage · {selectedNAIPYear?.gsd_m ?? naipAvailability.latest_per_tile_gsd_m} m</span><strong>{naipEstimatedPixels.toLocaleString()} pixels estimated</strong><small>License record: {naipAvailability.source_license_summary}</small>{naipSizeTooLarge && <small>Draw a smaller rectangle to stay below {(naipAvailability?.max_output_pixels || 0).toLocaleString()} pixels.</small>}</> : <span>Define an area to check coverage.</span>}
                </div>
              </>
            ) : (
              <>
                <label className="field-label">OSM feature type<div className="select-wrap"><select value={featureType} onChange={(event) => { setFeatureType(event.target.value); setFeatureSubtype('') }}>{featureTypes.map((item) => <option key={item} value={item}>{item}</option>)}</select><ChevronDown size={16} /></div></label>
                <label className="field-label">Subtype / tag value <em>Optional</em><input list="osm-subtypes" value={featureSubtype} onChange={(event) => setFeatureSubtype(event.target.value)} placeholder="All values" /><datalist id="osm-subtypes">{availableSubtypes.map((item) => <option key={item} value={item} />)}</datalist></label>
              </>
            )}
          </section>

            {error && <div className="error-message">{error}</div>}
            {currentJob && <div className="job-progress"><div><span>{currentJob.message}</span><strong>{currentJob.progress}%</strong></div><div className="progress-track"><i style={{ width: `${currentJob.progress}%` }} /></div></div>}
            <p className="source-note">{workflow === 'elevation' ? 'USGS 3DEP seamless source raster and lightweight preview are stored separately' : workflow === 'naip' ? 'NAIP imagery provided by USDA Farm Service Agency · AOI GeoTIFF and source-item manifest stored separately' : targetOSM ? `Adding to ${targetOSM.label} · Existing layers are preserved` : 'OpenStreetMap via Overpass · acceptable for modest, user-triggered local use only; not reliable or suitable for scaled or commercial deployment'}</p>
          </div>
          <div className="extract-actions">
            <button className="extract-button" disabled={busy || !backendOnline || (workflow === 'naip' && (naipAvailabilityLoading || !naipAvailability || naipSizeTooLarge))} onClick={extract}>{workflow === 'elevation' ? <Box size={18} /> : workflow === 'naip' ? <Images size={18} /> : <Archive size={18} />}{busy ? 'Working…' : workflow === 'elevation' ? 'Extract elevation' : workflow === 'naip' ? 'Extract NAIP imagery' : targetOSM ? 'Add feature classes' : `Build ${osmOutputFormatLabels[outputFormat]}`}</button>
          </div>
        </aside>

        <section className="canvas-workspace">
          <div className="map-pane pane">
            <div className="pane-header"><div><span className="pane-kicker">Shared selection</span><strong>Area of interest</strong></div><div className="pane-badge"><MapPin size={14} /> {selectedArea.toFixed(1)} km²</div></div>
            <MapSelector
              bounds={bounds}
              boundary={boundary}
              featureData={workflow === 'osm' ? osmPreview : null}
              featureDataLoading={workflow === 'osm' && osmPreviewLoading}
              featureDataError={workflow === 'osm' ? osmPreviewError : ''}
              onBoundsChange={setBounds}
              onBoundaryClear={clearBoundary}
            />
          </div>

          {workflow === 'elevation' ? (
            <div className="terrain-pane pane">
              <div className="pane-header terrain-header"><div><span className="pane-kicker">3D surface</span><strong>{active.label}</strong></div><div className="viewer-controls"><label className="exaggeration-control" title="ArcGIS-style vertical exaggeration: 0× is flat and 1× is real scale"><SlidersHorizontal size={14} /><input className="exaggeration-slider" aria-label="Vertical exaggeration slider" type="range" min="0" max="4" step="0.1" value={exaggeration} onChange={(event) => setExaggeration(Number(event.target.value))} /><input className="exaggeration-value" aria-label="Vertical exaggeration value" title="Enter a value from 0 to 4" type="number" min="0" max="4" step="0.1" value={exaggeration} onChange={(event) => setExaggeration(Math.min(4, Math.max(0, Number(event.target.value) || 0)))} /><b>×</b></label><button className={wireframe ? 'active' : ''} onClick={() => setWireframe((value) => !value)}>Mesh</button><button className={showSeaLevel ? 'active' : ''} aria-pressed={showSeaLevel} title="Show the 0 m sea-level reference" onClick={() => setShowSeaLevel((value) => !value)}>Sea level</button><div className="select-wrap compact"><select value={colorRamp} onChange={(event) => setColorRamp(event.target.value as ColorRamp)}><option value="topographic">Topo</option><option value="ember">Ember</option><option value="glacial">Glacial</option></select><ChevronDown size={13} /></div></div></div>
              <TerrainScene preview={active.preview} bounds={active.bounds} exaggeration={exaggeration} wireframe={wireframe} colorRamp={colorRamp} showSeaLevel={showSeaLevel} />
              <div className="terrain-stats"><Stat label="Low" value={stats.minimum.toLocaleString()} suffix=" m" /><Stat label="Mean" value={stats.mean.toLocaleString()} suffix=" m" /><Stat label="High" value={stats.maximum.toLocaleString()} suffix=" m" /><Stat label="Relief" value={stats.relief.toLocaleString()} suffix=" m" /></div>
              {active.id !== 'demo' && <div className="package-actions"><a className="download-button" href={active.files.package_download || `/api/datasets/${active.id}/download/package`}><Download size={15} /> Download DEM + sources</a>{active.files.documentation_download && <a className="manifest-download" href={active.files.documentation_download}><FileText size={15} /> Source documentation</a>}</div>}
            </div>
          ) : workflow === 'naip' ? (
            <div className="naip-pane pane">
              <div className="pane-header"><div><span className="pane-kicker">NAIP aerial imagery</span><strong>{activeNAIP?.label || 'Ready for a NAIP extraction'}</strong></div>{activeNAIP && <div className="pane-badge"><Images size={14} /> {activeNAIP.years.join(' / ')}</div>}</div>
              {activeNAIP ? <>
                <div className="naip-preview"><img src={activeNAIP.files.preview_download} alt={`NAIP preview for ${activeNAIP.label}`} /></div>
                <div className="naip-preview-footer"><div><span>{activeNAIP.acquisition_start?.slice(0, 10)}{activeNAIP.acquisition_end && activeNAIP.acquisition_end !== activeNAIP.acquisition_start ? ` – ${activeNAIP.acquisition_end.slice(0, 10)}` : ''}</span><strong>{activeNAIP.spatial.width.toLocaleString()} × {activeNAIP.spatial.height.toLocaleString()} · {activeNAIP.spatial.band_count} bands</strong><small className="naip-credit">{activeNAIP.attribution || 'NAIP imagery provided by USDA Farm Service Agency'}</small><small className="naip-credit">License record: {activeNAIP.source_license_summary || 'Not declared; verify before redistribution'}</small></div><a className="manifest-download" href={activeNAIP.files.manifest_download}><FileText size={15} /> Source manifest</a></div>
              </> : <div className="naip-empty"><span><Images size={34} /></span><h2>Select the newest imagery for this location</h2><p>{naipAvailabilityLoading ? 'Checking published NAIP acquisitions…' : naipAvailability ? `${naipAvailability.years.length} acquisition year${naipAvailability.years.length === 1 ? '' : 's'} found. Latest complete coverage: ${naipAvailability.latest_complete_year || 'not available'}.` : 'Draw a rectangle or search for a U.S. location to check coverage.'}</p></div>}
                {activeNAIP && <div className="package-actions"><a className="download-button" href={activeNAIP.files.package_download || `/api/naip/imagery/${activeNAIP.id}/download/package`}><Download size={15} /> Download imagery + sources</a>{activeNAIP.files.documentation_download && <a className="manifest-download" href={activeNAIP.files.documentation_download}><FileText size={15} /> Source documentation</a>}</div>}
            </div>
          ) : (
            <div className="osm-pane pane">
              <div className="pane-header"><div><span className="pane-kicker">{osmOutputFormatLabels[activeOSMFormat]} export</span><strong>{activeOSM?.label || 'Ready for an OSM extraction'}</strong></div>{activeOSM && <div className="pane-badge"><Archive size={14} /> {activeOSM.feature_count.toLocaleString()} features</div>}</div>
              <div className="osm-summary">
                <div className="osm-hero"><span><Archive size={30} /></span><h2>{activeOSM ? 'OSM dataset ready' : 'Use the shared map to define your extract'}</h2><p>{activeOSM ? `${activeOSM.feature_classes.length} feature class${activeOSM.feature_classes.length === 1 ? '' : 'es'} created from ${activeOSM.feature_type}${activeOSM.feature_subtype ? `=${activeOSM.feature_subtype}` : ''}.` : 'Choose a feature type and optional tag value. Geospatial Extraction Studio splits mixed geometries into GIS-ready feature classes.'}</p></div>
                {activeOSM && <><div className="osm-metrics"><Stat label="Features" value={activeOSM.feature_count.toLocaleString()} /><Stat label="Classes" value={activeOSM.feature_classes.length} /><Stat label="Area" value={activeOSM.area_km2.toLocaleString()} suffix=" km²" /></div><div className="class-list"><span>Feature classes</span>{activeOSM.feature_classes.map((item) => <code key={item}>{item}</code>)}</div><a className="osm-download" href={activeOSM.files.download}><Download size={17} /> Download {osmOutputFormatLabels[activeOSMFormat]} + attribution</a></>}
                <p className="license-note">© OpenStreetMap contributors · Open Data Commons Open Database License (ODbL) 1.0</p><p className="service-use-notice">Public OSM services are acceptable for modest, user-triggered local use. They are not reliable or suitable for scaled or commercial deployment; use a contracted or self-hosted provider first.</p>
              </div>
            </div>
          )}

          {workflow === 'elevation' ? (
            <div className="data-strip"><div className="dataset-summary"><span className="summary-icon"><Database size={18} /></span><div><span>{active.provider}</span><strong>{active.product}</strong></div></div><div className="metadata-pills"><span>CRS <b>{active.preview.spatial.crs}</b></span><span>Source grid <b>{active.preview.spatial.source_width} × {active.preview.spatial.source_height}</b></span><span>Preview <b>{active.preview.grid.columns} × {active.preview.grid.rows}</b></span><span>Vertical datum <b>{active.preview.spatial.vertical_datum}</b></span></div></div>
          ) : workflow === 'naip' ? (
            activeNAIP ? <div className="data-strip"><div className="dataset-summary"><span className="summary-icon"><Images size={18} /></span><div><span>{activeNAIP.provider}</span><strong>{activeNAIP.product}</strong></div></div><div className="metadata-pills"><span>Years <b>{activeNAIP.years.join(' / ')}</b></span><span>Resolution <b>{activeNAIP.spatial.resolution_m} m</b></span><span>CRS <b>{activeNAIP.spatial.crs}</b></span><span>Coverage <b>{activeNAIP.coverage_percent}%</b></span></div><a className="download-button" href={activeNAIP.files.package_download || `/api/naip/imagery/${activeNAIP.id}/download/package`}><Download size={15} /> Imagery + sources</a></div> : <div className="data-strip empty-strip">NAIP imagery details will appear here.</div>
          ) : activeOSM ? (
            <div className="data-strip"><div className="dataset-summary"><span className="summary-icon"><Archive size={18} /></span><div><span>{activeOSM.provider}</span><strong>{activeOSM.feature_type}{activeOSM.feature_subtype ? `=${activeOSM.feature_subtype}` : ''}</strong></div></div><div className="metadata-pills"><span>Format <b>{osmOutputFormatLabels[activeOSMFormat]}</b></span><span>License <b>ODbL 1.0</b></span><span>Archive <b>ZIP</b></span></div><a className="download-button" href={activeOSM.files.download}><Download size={15} /> Download</a></div>
          ) : <div className="data-strip empty-strip">OSM export details will appear here.</div>}

          {workflow === 'elevation' && recent.length > 0 && <div className="recent-strip"><span>Recent terrain</span>{recent.slice(0, 3).map((item) => <button key={item.id} onClick={() => setActive(item)}><Database size={13} />{item.label}</button>)}</div>}
          {workflow === 'naip' && recentNAIP.length > 0 && <div className="recent-strip"><span>Recent NAIP</span>{recentNAIP.slice(0, 3).map((item) => <button key={item.id} onClick={() => setActiveNAIP(item)}><Images size={13} />{item.label}</button>)}</div>}
          {workflow === 'osm' && recentOSM.length > 0 && <div className="recent-strip"><span>Recent OSM</span>{recentOSM.slice(0, 3).map((item) => <button key={item.id} onClick={() => setActiveOSM(item)}><Archive size={13} />{item.label}</button>)}</div>}
        </section>
      </main>
    </div>
  )
}
