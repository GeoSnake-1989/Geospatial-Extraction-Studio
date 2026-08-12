import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { BoundingBox, TerrainPreview } from '../types'

export type ColorRamp = 'topographic' | 'ember' | 'glacial'

type Props = {
  preview: TerrainPreview
  bounds: BoundingBox
  exaggeration: number
  wireframe: boolean
  colorRamp: ColorRamp
  showSeaLevel: boolean
}

type TerrainView = {
  preview: TerrainPreview
  bounds: BoundingBox
  position: THREE.Vector3
  target: THREE.Vector3
  zoom: number
}

function sameBounds(left: BoundingBox, right: BoundingBox) {
  return left.west === right.west
    && left.south === right.south
    && left.east === right.east
    && left.north === right.north
}

function geographicSceneDimensions(bounds: BoundingBox, rows: number, columns: number) {
  const centerLatitude = ((bounds.south + bounds.north) / 2) * (Math.PI / 180)
  const widthMeters = Math.abs(bounds.east - bounds.west) * 111_320 * Math.max(0.01, Math.cos(centerLatitude))
  const depthMeters = Math.abs(bounds.north - bounds.south) * 110_574

  if (!Number.isFinite(widthMeters) || !Number.isFinite(depthMeters) || Math.max(widthMeters, depthMeters) < 1) {
    const width = 10
    return { width, depth: Math.max(0.1, width * (rows / columns)), metersToScene: 0.01 }
  }

  const metersToScene = 10 / Math.max(widthMeters, depthMeters)
  return {
    width: Math.max(0.1, widthMeters * metersToScene),
    depth: Math.max(0.1, depthMeters * metersToScene),
    metersToScene,
  }
}

function seaReferencePosition(minimum: number, maximum: number, heightScale: number) {
  const elevationRange = Math.max(1, maximum - minimum)
  if (minimum <= 0 && maximum >= 0) return ((0 - minimum) / elevationRange) * heightScale
  const metersOutsideTerrain = minimum > 0 ? minimum : Math.abs(maximum)
  const compressedGap = 0.55 + Math.min(1.25, Math.log10(metersOutsideTerrain + 1) * 0.38)
  return minimum > 0 ? -compressedGap : heightScale + compressedGap
}

function formatSignedMeters(value: number) {
  const rounded = Math.round(value * 10) / 10
  return `${rounded > 0 ? '+' : rounded < 0 ? '−' : ''}${Math.abs(rounded).toLocaleString()} m`
}

function formatMeters(value: number) {
  return `${(Math.round(Math.abs(value) * 10) / 10).toLocaleString()} m`
}

function terrainColor(value: number, ramp: ColorRamp) {
  const stops: Record<ColorRamp, Array<[number, string]>> = {
    topographic: [[0, '#183c3a'], [0.28, '#4f7150'], [0.55, '#af9a62'], [0.78, '#8b6954'], [1, '#f0ead8']],
    ember: [[0, '#241637'], [0.32, '#6f2446'], [0.63, '#c85b3c'], [0.82, '#f1a94b'], [1, '#fff0bd']],
    glacial: [[0, '#092f45'], [0.35, '#176b79'], [0.62, '#6bb6b1'], [0.82, '#c2d9d0'], [1, '#ffffff']],
  }
  const palette = stops[ramp]
  for (let index = 1; index < palette.length; index += 1) {
    if (value <= palette[index][0]) {
      const [lowStop, lowColor] = palette[index - 1]
      const [highStop, highColor] = palette[index]
      return new THREE.Color(lowColor).lerp(new THREE.Color(highColor), (value - lowStop) / (highStop - lowStop))
    }
  }
  return new THREE.Color(palette[palette.length - 1][1])
}

export function TerrainScene({ preview, bounds, exaggeration, wireframe, colorRamp, showSeaLevel }: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const viewRef = useRef<TerrainView | null>(null)
  const [sample, setSample] = useState<number | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#101b19')
    scene.fog = new THREE.FogExp2('#101b19', 0.033)

    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100)
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.08
    renderer.shadowMap.enabled = true
    host.appendChild(renderer.domElement)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true
    controls.dampingFactor = 0.055
    controls.maxPolarAngle = Math.PI * 0.49

    const { rows, columns, values, valid_mask: validMask } = preview.grid
    const { minimum, maximum } = preview.statistics
    const elevationRange = Math.max(1, maximum - minimum)
    const { width, depth, metersToScene } = geographicSceneDimensions(bounds, rows, columns)
    // ArcGIS-style scaling: 1x uses the same scale for horizontal meters and elevation meters.
    const heightScale = elevationRange * metersToScene * exaggeration
    const seaLevelY = seaReferencePosition(minimum, maximum, heightScale)
    const verticalMinimum = showSeaLevel ? Math.min(0, seaLevelY) : 0
    const verticalMaximum = showSeaLevel ? Math.max(heightScale, seaLevelY) : heightScale
    const verticalCenter = (verticalMinimum + verticalMaximum) / 2
    const sceneSpan = Math.max(5, width, depth, verticalMaximum - verticalMinimum)
    camera.far = Math.max(100, sceneSpan * 12)
    camera.updateProjectionMatrix()
    controls.minDistance = Math.max(1, sceneSpan * 0.32)
    controls.maxDistance = Math.max(28, sceneSpan * 4)
    controls.target.set(0, verticalCenter, 0)
    camera.position.set(sceneSpan * 0.85, verticalCenter + sceneSpan * 0.7, sceneSpan * 1.05)

    const savedView = viewRef.current
    if (savedView?.preview === preview && sameBounds(savedView.bounds, bounds)) {
      camera.position.copy(savedView.position)
      camera.zoom = savedView.zoom
      controls.target.copy(savedView.target)
      camera.updateProjectionMatrix()
      controls.update()
    }

    const positions = new Float32Array(rows * columns * 3)
    const colors = new Float32Array(rows * columns * 3)
    const indices: number[] = []

    for (let row = 0; row < rows; row += 1) {
      for (let column = 0; column < columns; column += 1) {
        const offset = (row * columns + column) * 3
        const normalized = (values[row][column] - minimum) / elevationRange
        positions[offset] = (column / (columns - 1) - 0.5) * width
        positions[offset + 1] = (values[row][column] - minimum) * metersToScene * exaggeration
        positions[offset + 2] = (row / (rows - 1) - 0.5) * depth
        terrainColor(normalized, colorRamp).toArray(colors, offset)
      }
    }
    for (let row = 0; row < rows - 1; row += 1) {
      for (let column = 0; column < columns - 1; column += 1) {
        const a = row * columns + column
        const b = a + 1
        const c = a + columns
        const d = c + 1
        const aIsValid = validMask?.[row]?.[column] ?? true
        const bIsValid = validMask?.[row]?.[column + 1] ?? true
        const cIsValid = validMask?.[row + 1]?.[column] ?? true
        const dIsValid = validMask?.[row + 1]?.[column + 1] ?? true
        if (aIsValid && bIsValid && cIsValid) indices.push(a, c, b)
        if (bIsValid && cIsValid && dIsValid) indices.push(b, c, d)
      }
    }

    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    geometry.setIndex(indices)
    geometry.computeVertexNormals()
    const material = new THREE.MeshStandardMaterial({
      vertexColors: true,
      roughness: 0.82,
      metalness: 0.02,
      side: THREE.DoubleSide,
      wireframe,
    })
    const mesh = new THREE.Mesh(geometry, material)
    mesh.castShadow = true
    mesh.receiveShadow = true
    scene.add(mesh)

    const base = new THREE.Mesh(
      new THREE.BoxGeometry(width + 0.16, 0.32, depth + 0.16),
      new THREE.MeshStandardMaterial({ color: '#0b1312', roughness: 1 }),
    )
    base.position.y = -0.2
    base.receiveShadow = true
    scene.add(base)

    if (showSeaLevel) {
      const plane = new THREE.Mesh(
        new THREE.PlaneGeometry(width + 0.8, depth + 0.8),
        new THREE.MeshPhysicalMaterial({
          color: '#39b9dd',
          transparent: true,
          opacity: 0.3,
          roughness: 0.24,
          metalness: 0,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      )
      plane.rotation.x = -Math.PI / 2
      plane.position.y = seaLevelY
      plane.renderOrder = 3
      scene.add(plane)

      const gapHeight = Math.abs(seaLevelY)
      if (gapHeight > 0.02) {
        const volume = new THREE.Mesh(
          new THREE.BoxGeometry(width + 0.18, gapHeight, depth + 0.18),
          new THREE.MeshBasicMaterial({
            color: '#1689aa',
            transparent: true,
            opacity: 0.065,
            side: THREE.BackSide,
            depthWrite: false,
          }),
        )
        volume.position.y = seaLevelY / 2
        volume.renderOrder = 1
        scene.add(volume)
      }

      const gaugeX = width / 2 + 0.52
      const gaugeZ = depth / 2 + 0.5
      const gauge = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(gaugeX, 0, gaugeZ),
          new THREE.Vector3(gaugeX, seaLevelY, gaugeZ),
        ]),
        new THREE.LineBasicMaterial({ color: '#76ddf3', transparent: true, opacity: 0.95 }),
      )
      scene.add(gauge)
    }

    scene.add(new THREE.HemisphereLight('#dceadf', '#17312b', 1.8))
    const sun = new THREE.DirectionalLight('#ffe4ae', 3.2)
    sun.position.set(-6, 10, 8)
    sun.castShadow = true
    sun.shadow.mapSize.set(2048, 2048)
    scene.add(sun)
    const rim = new THREE.DirectionalLight('#6fc5bf', 1.1)
    rim.position.set(8, 4, -6)
    scene.add(rim)

    const raycaster = new THREE.Raycaster()
    const pointer = new THREE.Vector2()
    const onPointer = (event: PointerEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1
      raycaster.setFromCamera(pointer, camera)
      const hit = raycaster.intersectObject(mesh)[0]
      if (!hit) return setSample(null)
      const column = Math.max(0, Math.min(columns - 1, Math.round((hit.point.x / width + 0.5) * (columns - 1))))
      const row = Math.max(0, Math.min(rows - 1, Math.round((hit.point.z / depth + 0.5) * (rows - 1))))
      const value = values[row][column]
      setSample(Math.round(value * 10) / 10)
    }
    renderer.domElement.addEventListener('pointerdown', onPointer)

    const resize = () => {
      const widthPx = host.clientWidth
      const heightPx = host.clientHeight
      camera.aspect = widthPx / Math.max(1, heightPx)
      camera.updateProjectionMatrix()
      renderer.setSize(widthPx, heightPx, false)
    }
    const observer = new ResizeObserver(resize)
    observer.observe(host)
    resize()

    let frame = 0
    const animate = () => {
      controls.update()
      renderer.render(scene, camera)
      frame = requestAnimationFrame(animate)
    }
    animate()

    return () => {
      viewRef.current = {
        preview,
        bounds: { ...bounds },
        position: camera.position.clone(),
        target: controls.target.clone(),
        zoom: camera.zoom,
      }
      cancelAnimationFrame(frame)
      observer.disconnect()
      renderer.domElement.removeEventListener('pointerdown', onPointer)
      controls.dispose()
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Line) {
          object.geometry.dispose()
          const objectMaterials = Array.isArray(object.material) ? object.material : [object.material]
          objectMaterials.forEach((objectMaterial) => objectMaterial.dispose())
        }
      })
      renderer.dispose()
      host.removeChild(renderer.domElement)
    }
  }, [bounds, colorRamp, exaggeration, preview, showSeaLevel, wireframe])

  const floorElevation = preview.statistics.minimum
  const floorRelation = floorElevation > 0
    ? `${formatMeters(floorElevation)} above the 0 m reference`
    : floorElevation < 0
      ? `${formatMeters(floorElevation)} below the 0 m reference`
      : 'Terrain floor meets the 0 m reference'
  const datum = preview.spatial.vertical_datum
  const datumIsUncertain = /not declared|not applicable|source-dependent/i.test(datum)
  const seaGapIsCompressed = floorElevation > 0 || preview.statistics.maximum < 0

  return (
    <div ref={hostRef} className="terrain-canvas" aria-label="Interactive 3D terrain">
      {showSeaLevel && <div className="sea-datum-card">
        <div><span><i />Sea-level reference</span><b>0 m</b></div>
        <div><span>Terrain floor</span><b>{formatSignedMeters(floorElevation)}</b></div>
        <em>{floorRelation}</em>
        <small>{datumIsUncertain ? `Reference only · ${datum}` : `Vertical datum · ${datum}`}{seaGapIsCompressed ? ' · visual gap compressed' : ''}</small>
      </div>}
      <div className="terrain-help">Drag to orbit · Scroll to zoom · Click to sample</div>
      {sample !== null && <div className="terrain-sample">{sample.toLocaleString()} m</div>}
    </div>
  )
}
