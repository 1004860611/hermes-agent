export interface RenderFace {
  face_index: number
  indices: number[]
  positions: number[]
}

export interface GeometryReference {
  index: number
  kind: 'edge' | 'face' | 'solid' | 'vertex'
}

export interface MergedFaceGroup {
  count: number
  faceIndex: number
  start: number
}

export interface MergedFaceMeshData {
  groups: MergedFaceGroup[]
  indices: Uint32Array
  positions: Float32Array
  triangleFaceIndices: Uint32Array
}

const MAX_UINT32 = 0xffffffff
const MAX_FLOAT32 = 3.4028234663852886e38

/** Resolve exact face references and AAG edge references to stable OCCT face IDs. */
export function resolveGeometryRefFaceIndices(
  refs: GeometryReference[] | undefined,
  edgeFaces: Map<number, number[]>
): Set<number> {
  const faceIndices = new Set(refs?.filter(ref => ref.kind === 'face').map(ref => ref.index) ?? [])

  for (const ref of refs ?? []) {
    if (ref.kind !== 'edge') {
      continue
    }

    for (const faceIndex of edgeFaces.get(ref.index) ?? []) {
      faceIndices.add(faceIndex)
    }
  }

  return faceIndices
}

function validateFace(face: RenderFace, seen: Set<number>): void {
  if (!Number.isInteger(face.face_index) || face.face_index <= 0 || face.face_index > MAX_UINT32) {
    throw new Error(`无效的 OCCT 面索引：${face.face_index}`)
  }

  if (seen.has(face.face_index)) {
    throw new Error(`重复的 OCCT 面索引：${face.face_index}`)
  }

  seen.add(face.face_index)

  if (face.positions.length < 9 || face.positions.length % 3 !== 0) {
    throw new Error(`面 #${face.face_index} 的顶点数据无效`)
  }

  if (face.indices.length < 3 || face.indices.length % 3 !== 0) {
    throw new Error(`面 #${face.face_index} 的三角形索引无效`)
  }

  for (const value of face.positions) {
    if (!Number.isFinite(value) || Math.abs(value) > MAX_FLOAT32) {
      throw new Error(`面 #${face.face_index} 包含无法渲染的坐标`)
    }
  }

  const vertexCount = face.positions.length / 3

  for (const index of face.indices) {
    if (!Number.isInteger(index) || index < 0 || index >= vertexCount) {
      throw new Error(`面 #${face.face_index} 包含越界的三角形索引`)
    }
  }
}

/** Merge exact OCCT face meshes into the grouped layout used by testUG_WEB. */
export function mergeRenderFaces(faces: RenderFace[]): MergedFaceMeshData {
  if (faces.length === 0) {
    throw new Error('OCCT 网格中没有可显示的面')
  }

  const seen = new Set<number>()
  let positionCount = 0
  let indexCount = 0

  for (const face of faces) {
    validateFace(face, seen)
    positionCount += face.positions.length
    indexCount += face.indices.length
  }

  if (!Number.isSafeInteger(positionCount) || !Number.isSafeInteger(indexCount)) {
    throw new Error('OCCT 网格数据过大，无法安全渲染')
  }

  const positions = new Float32Array(positionCount)
  const indices = new Uint32Array(indexCount)
  const triangleFaceIndices = new Uint32Array(indexCount / 3)
  const groups: MergedFaceGroup[] = []
  let positionOffset = 0
  let indexOffset = 0
  let triangleOffset = 0
  let vertexOffset = 0

  for (const face of faces) {
    positions.set(face.positions, positionOffset)

    for (let index = 0; index < face.indices.length; index += 1) {
      indices[indexOffset + index] = face.indices[index] + vertexOffset
    }

    const triangleCount = face.indices.length / 3
    triangleFaceIndices.fill(face.face_index, triangleOffset, triangleOffset + triangleCount)
    groups.push({ count: face.indices.length, faceIndex: face.face_index, start: indexOffset })

    positionOffset += face.positions.length
    indexOffset += face.indices.length
    triangleOffset += triangleCount
    vertexOffset += face.positions.length / 3
  }

  return { groups, indices, positions, triangleFaceIndices }
}
