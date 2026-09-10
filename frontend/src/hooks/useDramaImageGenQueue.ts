/** 订阅漫剧生图全局队列快照 */
import { useSyncExternalStore } from 'react'
import {
  getDramaImageGenQueue,
  subscribeDramaImageGenQueue,
  type DramaImageGenJob,
} from '../lib/dramaImageGenQueue'

// Hook：返回当前生图队列列表
export function useDramaImageGenQueue(): DramaImageGenJob[] {
  return useSyncExternalStore(subscribeDramaImageGenQueue, getDramaImageGenQueue, getDramaImageGenQueue)
}

// Hook：某资产是否在排队或生成中
export function useDramaAssetImageBusy(assetId: number): boolean {
  const queue = useDramaImageGenQueue()
  return queue.some(
    (job) =>
      job.assetId === assetId && (job.status === 'queued' || job.status === 'running'),
  )
}
