import { describe, expect, it } from 'vitest'
import { ApiError } from '../../lib/api'
import { errDetails, errText, num, optNum, reqNum, vnDateToIso } from './lib'

describe('ops lib', () => {
  it('vnDateToIso: ngày VN -> UTC, end = đầu ngày hôm sau', () => {
    expect(vnDateToIso('2025-09-01')).toBe('2025-08-31T17:00:00.000Z')
    expect(vnDateToIso('2025-09-01', true)).toBe('2025-09-01T17:00:00.000Z')
    expect(vnDateToIso('')).toBeUndefined()
  })
  it('errText gộp chi tiết 422 dạng {loc,msg} và chuỗi', () => {
    const e = new ApiError(422, 'VALIDATION', 'Dữ liệu không hợp lệ', [{ loc: ['body', 'code'], msg: 'sai' }, 'hysteresis trong [0, 0.3)'])
    expect(errDetails(e)).toEqual(['code: sai', 'hysteresis trong [0, 0.3)'])
    expect(errText(e)).toBe('Dữ liệu không hợp lệ — code: sai; hysteresis trong [0, 0.3)')
  })
  it('optNum/reqNum chuyển chuỗi input', () => {
    expect(optNum(num().min(0)).parse('')).toBeUndefined()
    expect(optNum(num().min(0)).parse('2.5')).toBe(2.5)
    expect(reqNum(num()).safeParse('').success).toBe(false)
    expect(reqNum(num()).safeParse('abc').success).toBe(false)
  })
})
