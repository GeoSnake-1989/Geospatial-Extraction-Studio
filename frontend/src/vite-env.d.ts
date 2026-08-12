/// <reference types="vite/client" />

declare module '*.css'

interface ImportMetaEnv {
  readonly VITE_OSM_TILE_ATTRIBUTION?: string
  readonly VITE_OSM_TILE_LICENSE_URL?: string
  readonly VITE_OSM_TILE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
