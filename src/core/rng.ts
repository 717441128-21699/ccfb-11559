/** 可复现的 mulberry32 伪随机数，保证每次生成的馆数据一致 */
export class Rng {
  private s: number;

  constructor(seed: number) {
    this.s = seed >>> 0;
  }

  next(): number {
    this.s = (this.s + 0x6d2b79f5) >>> 0;
    let t = this.s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  }

  int(min: number, max: number): number {
    return min + Math.floor(this.next() * (max - min + 1));
  }

  pick<T>(arr: readonly T[]): T {
    return arr[Math.floor(this.next() * arr.length)];
  }
}

const NAME_A = ['恒', '瑞', '华', '博', '天', '远', '联', '创', '金', '海', '智', '云', '星', '泰', '安'];
const NAME_B = ['达', '业', '科', '信', '源', '通', '展', '贸', '电', '力', '能', '材', '机', '讯', '成'];
const NAME_C = ['科技', '实业', '集团', '股份', '机电', '智能', '新材料', '国际', '装备', '光电'];

/** 生成 2~8 字的中文展商名，用于门头排版测试 */
export function randomCompanyName(rng: Rng): string {
  const len = rng.int(2, 8);
  const parts: string[] = [];
  const two = rng.next() > 0.4;
  parts.push(rng.pick(NAME_A), rng.pick(NAME_B));
  if (two) parts.push(rng.pick(NAME_C));
  let name = parts.join('');
  if (name.length > len) name = name.slice(0, len);
  return name;
}
