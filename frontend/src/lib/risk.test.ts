import { describe, expect, it } from 'vitest'
import { floodCause } from './risk'

describe('floodCause', () => {
  it('ghép nguyên nhân và độ sâu', () => {
    expect(floodCause('TIDE', 40)).toBe('Ngập do triều, khoảng 40 cm (ước tính)')
    expect(floodCause('RAIN_TIDE', null)).toBe('Ngập do mưa kết hợp triều')
    expect(floodCause('REPORT')).toBe('Người dân báo ngập')
  })
  it('không có nguyên nhân thì null', () => {
    expect(floodCause(null, 30)).toBeNull()
    expect(floodCause(undefined)).toBeNull()
  })
})
