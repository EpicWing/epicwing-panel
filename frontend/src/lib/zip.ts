export interface ZipItem {
  name: string;
  data: Uint8Array;
  mtime: number;
  dir?: boolean;
}

const TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let value = n;
    for (let bit = 0; bit < 8; bit += 1) {
      value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
    }
    table[n] = value >>> 0;
  }
  return table;
})();

function crc32(data: Uint8Array): number {
  let crc = 0xffffffff;
  for (let i = 0; i < data.length; i += 1) {
    crc = (TABLE[(crc ^ (data[i] as number)) & 0xff] as number) ^ (crc >>> 8);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function dosStamp(seconds: number): { time: number; date: number } {
  const moment = new Date(seconds * 1000);
  const year = Math.max(1980, moment.getFullYear());
  return {
    time: (moment.getHours() << 11) | (moment.getMinutes() << 5) | (moment.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((moment.getMonth() + 1) << 5) | moment.getDate(),
  };
}

// ZIP without compression (store), UTF-8 names, no ZIP64: enough for archives under 4 GiB and 65535 entries.
export function buildZip(items: ZipItem[]): Blob {
  const encoder = new TextEncoder();
  const records = items.map((item) => ({
    item,
    name: encoder.encode(item.dir ? `${item.name}/` : item.name),
    crc: crc32(item.data),
    stamp: dosStamp(item.mtime),
    offset: 0,
  }));

  let size = 22;
  for (const record of records) size += 76 + 2 * record.name.length + record.item.data.length;
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);

  let pos = 0;
  for (const record of records) {
    const length = record.item.data.length;
    record.offset = pos;
    view.setUint32(pos, 0x04034b50, true);
    view.setUint16(pos + 4, 20, true);
    view.setUint16(pos + 6, 0x0800, true);
    view.setUint16(pos + 8, 0, true);
    view.setUint16(pos + 10, record.stamp.time, true);
    view.setUint16(pos + 12, record.stamp.date, true);
    view.setUint32(pos + 14, record.crc, true);
    view.setUint32(pos + 18, length, true);
    view.setUint32(pos + 22, length, true);
    view.setUint16(pos + 26, record.name.length, true);
    view.setUint16(pos + 28, 0, true);
    out.set(record.name, pos + 30);
    out.set(record.item.data, pos + 30 + record.name.length);
    pos += 30 + record.name.length + length;
  }

  const directory = pos;
  for (const record of records) {
    const length = record.item.data.length;
    view.setUint32(pos, 0x02014b50, true);
    view.setUint16(pos + 4, 20, true);
    view.setUint16(pos + 6, 20, true);
    view.setUint16(pos + 8, 0x0800, true);
    view.setUint16(pos + 10, 0, true);
    view.setUint16(pos + 12, record.stamp.time, true);
    view.setUint16(pos + 14, record.stamp.date, true);
    view.setUint32(pos + 16, record.crc, true);
    view.setUint32(pos + 20, length, true);
    view.setUint32(pos + 24, length, true);
    view.setUint16(pos + 28, record.name.length, true);
    view.setUint16(pos + 30, 0, true);
    view.setUint16(pos + 32, 0, true);
    view.setUint16(pos + 34, 0, true);
    view.setUint16(pos + 36, 0, true);
    view.setUint32(pos + 38, record.item.dir ? 0x10 : 0, true);
    view.setUint32(pos + 42, record.offset, true);
    out.set(record.name, pos + 46);
    pos += 46 + record.name.length;
  }

  view.setUint32(pos, 0x06054b50, true);
  view.setUint16(pos + 4, 0, true);
  view.setUint16(pos + 6, 0, true);
  view.setUint16(pos + 8, records.length, true);
  view.setUint16(pos + 10, records.length, true);
  view.setUint32(pos + 12, pos - directory, true);
  view.setUint32(pos + 16, directory, true);
  view.setUint16(pos + 20, 0, true);

  return new Blob([out], { type: "application/zip" });
}
