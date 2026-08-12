import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import type { BoundingBox, GeoJSONBoundary, OSMMapFeature, OSMMapPreview } from '../types'

type Props = {
  bounds: BoundingBox
  boundary: GeoJSONBoundary | null
  featureData: OSMMapPreview | null
  featureDataLoading: boolean
  featureDataError: string
  onBoundsChange: (bounds: BoundingBox) => void
  onBoundaryClear: () => void
}

const defaultTileUrl = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png'
const osmDataAttribution = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
const defaultTileAttribution = `Map data ${osmDataAttribution}`
const configuredTileUrl = import.meta.env.VITE_OSM_TILE_URL?.trim()
const configuredTileAttribution = import.meta.env.VITE_OSM_TILE_ATTRIBUTION?.trim()
const configuredTileLicenseUrl = import.meta.env.VITE_OSM_TILE_LICENSE_URL?.trim()
const configuredTileValues = [
  configuredTileUrl,
  configuredTileAttribution,
  configuredTileLicenseUrl,
]
const customTileConfigurationIsComplete = configuredTileValues.every(Boolean)
const customTileConfigurationIsPresent = configuredTileValues.some(Boolean)

if (customTileConfigurationIsPresent && !customTileConfigurationIsComplete) {
  throw new Error(
    'Incomplete custom tile configuration. Set VITE_OSM_TILE_URL, VITE_OSM_TILE_ATTRIBUTION, and VITE_OSM_TILE_LICENSE_URL together.',
  )
}

function checkedHttpUrl(value: string, label: string) {
  const parsed = new URL(value)
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error(`${label} must use HTTP or HTTPS.`)
  }
  return parsed.toString()
}

function escapeHtmlAttribute(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('"', '&quot;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
}

const tileUrl = customTileConfigurationIsComplete
  ? checkedHttpUrl(configuredTileUrl!, 'VITE_OSM_TILE_URL')
  : defaultTileUrl
const tileLicenseUrl = customTileConfigurationIsComplete
  ? checkedHttpUrl(configuredTileLicenseUrl!, 'VITE_OSM_TILE_LICENSE_URL')
  : ''
const tileAttribution = customTileConfigurationIsComplete
  ? `${configuredTileAttribution!} · <a href="${escapeHtmlAttribute(tileLicenseUrl)}" target="_blank" rel="noopener noreferrer">Tile provider terms</a> | Search and OSM data ${osmDataAttribution}`
  : defaultTileAttribution
const selectionStyle = { color: '#e2b96f', weight: 2, fillColor: '#e2b96f', fillOpacity: 0.13 }
function featurePopup(feature: OSMMapFeature, fallbackTitle: string) {
  const properties = feature.properties || {}
  const popup = document.createElement('div')
  popup.className = 'feature-popup'
  const title = document.createElement('strong')
  title.textContent = String(properties.name || properties._layer || fallbackTitle)
  popup.appendChild(title)
  const entries = Object.entries(properties)
    .filter(([key, value]) => key !== 'name' && key !== '_layer' && value !== null && value !== '' && value !== undefined)
    .slice(0, 7)
  for (const [key, value] of entries) {
    const row = document.createElement('span')
    const label = document.createElement('b')
    label.textContent = key.replaceAll('_', ' ')
    row.appendChild(label)
    row.appendChild(document.createTextNode(String(value)))
    popup.appendChild(row)
  }
  return popup
}

type DrawStart = {
  pointerId: number
  point: L.Point
  latLng: L.LatLng
}

export function MapSelector({
  bounds,
  boundary,
  featureData,
  featureDataLoading,
  featureDataError,
  onBoundsChange,
  onBoundaryClear,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const selectionRef = useRef<L.FeatureGroup | null>(null)
  const featureLayerRef = useRef<L.GeoJSON | null>(null)
  const draftRef = useRef<L.Rectangle | null>(null)
  const drawStartRef = useRef<DrawStart | null>(null)
  const drawingRef = useRef(false)
  const callbackRef = useRef(onBoundsChange)
  const boundaryClearRef = useRef(onBoundaryClear)
  const [drawing, setDrawing] = useState(false)
  const [drawHint, setDrawHint] = useState('Drag diagonally across the map to define the area')
  callbackRef.current = onBoundsChange
  boundaryClearRef.current = onBoundaryClear

  const setDrawingEnabled = (enabled: boolean, hint?: string) => {
    const map = mapRef.current
    drawingRef.current = enabled
    setDrawing(enabled)
    setDrawHint(hint || 'Drag diagonally across the map to define the area')
    if (!map) return
    if (enabled) {
      map.dragging.disable()
      map.touchZoom.disable()
      map.boxZoom.disable()
    } else {
      map.dragging.enable()
      map.touchZoom.enable()
      map.boxZoom.enable()
      drawStartRef.current = null
      if (draftRef.current && map.hasLayer(draftRef.current)) map.removeLayer(draftRef.current)
      draftRef.current = null
    }
  }

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    const map = L.map(containerRef.current, {
      center: [39.2, -98.4],
      zoom: 4,
      zoomControl: false,
      attributionControl: true,
    })
    mapRef.current = map
    L.control.zoom({ position: 'bottomright' }).addTo(map)
    L.tileLayer(tileUrl, {
      maxZoom: 19,
      attribution: tileAttribution,
    }).addTo(map)
    map.createPane('osmFeatures')
    map.getPane('osmFeatures')!.style.zIndex = '450'

    const selection = new L.FeatureGroup().addTo(map)
    selectionRef.current = selection

    const container = containerRef.current
    const pointFromEvent = (event: PointerEvent) => {
      const rectangle = container.getBoundingClientRect()
      return L.point(event.clientX - rectangle.left, event.clientY - rectangle.top)
    }
    const removeDraft = () => {
      if (draftRef.current && map.hasLayer(draftRef.current)) map.removeLayer(draftRef.current)
      draftRef.current = null
      drawStartRef.current = null
    }
    const onPointerDown = (event: PointerEvent) => {
      if (!drawingRef.current || (event.pointerType === 'mouse' && event.button !== 0)) return
      event.preventDefault()
      event.stopPropagation()
      container.setPointerCapture(event.pointerId)
      const point = pointFromEvent(event)
      const latLng = map.containerPointToLatLng(point)
      removeDraft()
      drawStartRef.current = { pointerId: event.pointerId, point, latLng }
      draftRef.current = L.rectangle(L.latLngBounds(latLng, latLng), selectionStyle).addTo(map)
      setDrawHint('Keep dragging, then release to finish')
    }
    const onPointerMove = (event: PointerEvent) => {
      const start = drawStartRef.current
      const draft = draftRef.current
      if (!drawingRef.current || !start || !draft || start.pointerId !== event.pointerId) return
      event.preventDefault()
      event.stopPropagation()
      draft.setBounds(L.latLngBounds(start.latLng, map.containerPointToLatLng(pointFromEvent(event))))
    }
    const onPointerUp = (event: PointerEvent) => {
      const start = drawStartRef.current
      const layer = draftRef.current
      if (!drawingRef.current || !start || !layer || start.pointerId !== event.pointerId) return
      event.preventDefault()
      event.stopPropagation()
      if (container.hasPointerCapture(event.pointerId)) container.releasePointerCapture(event.pointerId)
      const endPoint = pointFromEvent(event)
      if (Math.abs(endPoint.x - start.point.x) < 8 || Math.abs(endPoint.y - start.point.y) < 8) {
        removeDraft()
        setDrawHint('The area was too small. Drag diagonally to make a visible rectangle.')
        return
      }

      boundaryClearRef.current()
      selection.clearLayers()
      if (map.hasLayer(layer)) map.removeLayer(layer)
      selection.addLayer(layer)
      const next = layer.getBounds()
      draftRef.current = null
      drawStartRef.current = null
      callbackRef.current({
        west: Number(next.getWest().toFixed(6)),
        south: Number(next.getSouth().toFixed(6)),
        east: Number(next.getEast().toFixed(6)),
        north: Number(next.getNorth().toFixed(6)),
      })
      setDrawingEnabled(false)
    }
    const onPointerCancel = (event: PointerEvent) => {
      if (drawStartRef.current?.pointerId !== event.pointerId) return
      removeDraft()
      setDrawHint('Drawing canceled. Drag diagonally across the map to try again.')
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && drawingRef.current) setDrawingEnabled(false)
    }
    container.addEventListener('pointerdown', onPointerDown)
    container.addEventListener('pointermove', onPointerMove)
    container.addEventListener('pointerup', onPointerUp)
    container.addEventListener('pointercancel', onPointerCancel)
    window.addEventListener('keydown', onKeyDown)

    window.setTimeout(() => map.invalidateSize(), 0)
    return () => {
      container.removeEventListener('pointerdown', onPointerDown)
      container.removeEventListener('pointermove', onPointerMove)
      container.removeEventListener('pointerup', onPointerUp)
      container.removeEventListener('pointercancel', onPointerCancel)
      window.removeEventListener('keydown', onKeyDown)
      map.remove()
      mapRef.current = null
      selectionRef.current = null
      featureLayerRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const selection = selectionRef.current
    if (!map || !selection) return
    const leafletBounds = L.latLngBounds([bounds.south, bounds.west], [bounds.north, bounds.east])
    selection.clearLayers()
    if (boundary) {
      const boundaryLayer = L.geoJSON(boundary as never, {
        style: { color: '#e2b96f', weight: 3, fillColor: '#e2b96f', fillOpacity: 0.1 },
      }).addTo(selection)
      map.fitBounds(boundaryLayer.getBounds().pad(0.08), { maxZoom: 12, animate: true })
      return
    }
    L.rectangle(leafletBounds, selectionStyle).addTo(selection)
    map.fitBounds(leafletBounds.pad(0.55), { maxZoom: 12, animate: true })
  }, [boundary, bounds.east, bounds.north, bounds.south, bounds.west])

  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    if (featureLayerRef.current) {
      map.removeLayer(featureLayerRef.current)
      featureLayerRef.current = null
    }
    if (!featureData?.features.length) return

    const featureLayer = L.geoJSON(featureData as never, {
      pane: 'osmFeatures',
      style: (feature) => {
        const geometryType = feature?.geometry?.type || ''
        if (geometryType.includes('Polygon')) {
          return { pane: 'osmFeatures', color: '#64d5bb', weight: 1.5, fillColor: '#64d5bb', fillOpacity: 0.22 }
        }
        return { pane: 'osmFeatures', color: '#67d9c1', weight: 3, opacity: 0.95 }
      },
      pointToLayer: (_feature, latLng) => L.circleMarker(latLng, {
        pane: 'osmFeatures',
        radius: 5,
        color: '#10201c',
        weight: 1.5,
        fillColor: '#6fe1c8',
        fillOpacity: 1,
      }),
      onEachFeature: (rawFeature, layer) => {
        layer.bindPopup(featurePopup(rawFeature as unknown as OSMMapFeature, 'OpenStreetMap feature'), { maxWidth: 280 })
      },
    }).addTo(map)
    featureLayerRef.current = featureLayer
    const dataBounds = featureLayer.getBounds()
    if (dataBounds.isValid()) map.fitBounds(dataBounds.pad(0.16), { maxZoom: 15, animate: true })
  }, [featureData])

  return <div className={`map-selector ${drawing ? 'drawing' : ''}`}>
    <div ref={containerRef} className="map-canvas" aria-label="Map for selecting an extraction area" />
    <button
      type="button"
      className={`rectangle-tool ${drawing ? 'active' : ''}`}
      aria-pressed={drawing}
      aria-label={drawing ? 'Cancel rectangle drawing' : 'Draw a rectangle'}
      title={drawing ? 'Cancel drawing' : 'Draw a rectangle'}
      onClick={() => setDrawingEnabled(!drawingRef.current)}
    ><span aria-hidden="true">▱</span></button>
    {drawing && <div className="draw-guidance">{drawHint}<kbd>Esc</kbd></div>}
    {!drawing && featureDataLoading && <div className="map-data-status loading">Loading extracted features…</div>}
    {!drawing && featureDataError && <div className="map-data-status error">{featureDataError}</div>}
    {!drawing && featureData && !featureDataError && <div className="map-data-status">
      <i aria-hidden="true" />
      <span><strong>{featureData.displayed_feature_count.toLocaleString()}</strong> mapped feature{featureData.displayed_feature_count === 1 ? '' : 's'} · {featureData.layers.length} layer{featureData.layers.length === 1 ? '' : 's'}{featureData.truncated ? ` · preview of ${featureData.feature_count.toLocaleString()}` : ''}</span>
    </div>}
  </div>
}
