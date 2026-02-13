import React from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import ErrorPage from '@/app/error'

describe('error boundary (error.tsx)', () => {
  it('renders error message', () => {
    const error = Object.assign(new globalThis.Error('Test failure'), { digest: undefined })
    const reset = vi.fn()
    render(<ErrorPage error={error} reset={reset} />)
    expect(screen.getByText('Something went wrong')).toBeDefined()
    expect(screen.getByText('Test failure')).toBeDefined()
  })

  it('renders Try again button', () => {
    const error = Object.assign(new globalThis.Error('Oops'), { digest: undefined })
    const reset = vi.fn()
    render(<ErrorPage error={error} reset={reset} />)
    expect(screen.getByText('Try again')).toBeDefined()
  })

  it('calls reset when Try again is clicked', () => {
    const error = Object.assign(new globalThis.Error('Oops'), { digest: undefined })
    const reset = vi.fn()
    render(<ErrorPage error={error} reset={reset} />)
    fireEvent.click(screen.getByText('Try again'))
    expect(reset).toHaveBeenCalledOnce()
  })

  it('renders fallback when error.message is empty', () => {
    const error = Object.assign(new globalThis.Error(''), { digest: undefined })
    const reset = vi.fn()
    render(<ErrorPage error={error} reset={reset} />)
    expect(screen.getByText('Something went wrong')).toBeDefined()
    // With empty message, fallback text should show
    expect(screen.getByText('An unexpected error occurred.')).toBeDefined()
  })
})
