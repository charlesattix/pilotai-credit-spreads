import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(value)
}

export function formatPercent(value: number): string {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}%`
}

export function formatDate(date: string | Date): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(new Date(date))
}

export function formatDateTime(date: string | Date): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
  }).format(new Date(date))
}

export function getScoreColor(score: number): string {
  if (score >= 70) return 'text-profit'
  if (score >= 60) return 'text-yellow-500'
  if (score >= 50) return 'text-orange-500'
  return 'text-loss'
}

export function getScoreBgColor(score: number): string {
  if (score >= 70) return 'bg-profit/10 border-profit/30'
  if (score >= 60) return 'bg-yellow-500/10 border-yellow-500/30'
  if (score >= 50) return 'bg-orange-500/10 border-orange-500/30'
  return 'bg-loss/10 border-loss/30'
}
