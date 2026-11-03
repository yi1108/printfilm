// 后端维护的系统提示同步给前端，以便切换语言时重绘已经收到的提示。
import { readFileSync, writeFileSync } from 'node:fs'
const source = new URL('../backend/app/marketplace/locale_messages.json', import.meta.url)
const target = new URL('../frontend/src/features/marketplace/locale-server.json', import.meta.url)
writeFileSync(target, JSON.stringify(JSON.parse(readFileSync(source, 'utf8')), null, 2) + '\n')
