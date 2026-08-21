import { describe, expect, it } from 'vitest'

import { mergeRenderFaces, resolveGeometryRefFaceIndices } from './dfm-viewer-geometry'

describe('resolveGeometryRefFaceIndices', () => {
  it('merges explicit feature faces with faces adjacent to referenced problem edges', () => {
    const result = resolveGeometryRefFaceIndices(
      [
        { index: 7, kind: 'face' },
        { index: 12, kind: 'edge' },
        { index: 3, kind: 'vertex' }
      ],
      new Map([[12, [7, 9]]])
    )

    expect(Array.from(result).sort((left, right) => left - right)).toEqual([7, 9])
  })
})

describe('mergeRenderFaces', () => {
  it('merges OCCT faces into material groups without changing stable face indices', () => {
    const merged = mergeRenderFaces([
      {
        face_index: 2,
        indices: [0, 1, 2],
        positions: [0, 0, 0, 1, 0, 0, 0, 1, 0]
      },
      {
        face_index: 7,
        indices: [0, 1, 2, 0, 2, 3],
        positions: [0, 0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1]
      }
    ])

    expect(Array.from(merged.indices)).toEqual([0, 1, 2, 3, 4, 5, 3, 5, 6])
    expect(merged.groups).toEqual([
      { count: 3, faceIndex: 2, start: 0 },
      { count: 6, faceIndex: 7, start: 3 }
    ])
    expect(Array.from(merged.triangleFaceIndices)).toEqual([2, 7, 7])
  })

  it('rejects a duplicate face identity', () => {
    const face = {
      face_index: 1,
      indices: [0, 1, 2],
      positions: [0, 0, 0, 1, 0, 0, 0, 1, 0]
    }

    expect(() => mergeRenderFaces([face, face])).toThrow('重复的 OCCT 面索引')
  })

  it('rejects an index outside the face vertex buffer', () => {
    expect(() =>
      mergeRenderFaces([
        {
          face_index: 1,
          indices: [0, 1, 3],
          positions: [0, 0, 0, 1, 0, 0, 0, 1, 0]
        }
      ])
    ).toThrow('越界的三角形索引')
  })
})
