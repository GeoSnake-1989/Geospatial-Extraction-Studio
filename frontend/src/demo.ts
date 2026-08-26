import type { DatasetResult } from './types'

const rows = 56
const columns = 64
const values: number[][] = []
let minimum = Infinity
let maximum = -Infinity
let total = 0

for (let row = 0; row < rows; row += 1) {
  const line: number[] = []
  for (let column = 0; column < columns; column += 1) {
    const x = column / (columns - 1)
    const y = row / (rows - 1)
    const ridge = 720 * Math.exp(-Math.pow((x - 0.58) * 3.1, 2)) * (0.55 + 0.45 * Math.sin(y * 8.2 + x * 4))
    const shoulder = 330 * Math.exp(-((x - 0.26) ** 2 + (y - 0.34) ** 2) * 15)
    const valley = -190 * Math.exp(-((x - 0.48) ** 2) * 120) * (0.35 + y)
    const detail = 54 * Math.sin(x * 19 + y * 5) * Math.cos(y * 17)
    const elevation = Math.round(315 + ridge + shoulder + valley + detail)
    line.push(elevation)
    minimum = Math.min(minimum, elevation)
    maximum = Math.max(maximum, elevation)
    total += elevation
  }
  values.push(line)
}

export const demoDataset: DatasetResult = {
  id: 'demo',
  label: 'Terrain preview',
  provider: 'Illustrative surface',
  product: 'Procedural preview — extract a location for real USGS data',
  bounds: { west: -82.61, south: 27.91, east: -82.49, north: 28.01 },
  area_km2: 0,
  preview: {
    grid: { rows, columns, values, nodata_cells: 0 },
    statistics: {
      minimum,
      maximum,
      mean: Math.round(total / (rows * columns)),
      relief: maximum - minimum,
    },
    spatial: {
      crs: 'Preview only',
      horizontal_units: '—',
      bounds: [-82.61, 27.91, -82.49, 28.01],
      source_width: columns,
      source_height: rows,
      preview_width: columns,
      preview_height: rows,
      nodata: null,
      vertical_units: 'meters (illustrative)',
      vertical_datum: 'Not applicable',
    },
  },
  provenance: {
    attribution: 'Illustrative surface generated in the browser',
    license: 'Not source elevation data',
    vertical_datum: 'Not applicable',
  },
  files: { original: '', processed: '' },
}
