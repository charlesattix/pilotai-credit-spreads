import React from 'react'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from '@/components/ui/card'

describe('Badge component', () => {
  it('renders with default variant', () => {
    render(<Badge>Test</Badge>)
    expect(screen.getByText('Test')).toBeDefined()
  })

  it('renders with profit variant', () => {
    render(<Badge variant="profit">+$120</Badge>)
    expect(screen.getByText('+$120')).toBeDefined()
  })

  it('renders with loss variant', () => {
    render(<Badge variant="loss">-$50</Badge>)
    expect(screen.getByText('-$50')).toBeDefined()
  })

  it('renders with destructive variant', () => {
    render(<Badge variant="destructive">Error</Badge>)
    expect(screen.getByText('Error')).toBeDefined()
  })

  it('applies custom className', () => {
    const { container } = render(<Badge className="custom-class">X</Badge>)
    expect(container.firstChild).toHaveClass('custom-class')
  })
})

describe('Button component', () => {
  it('renders with default variant', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByText('Click me')).toBeDefined()
  })

  it('renders with all variants', () => {
    const variants = ['default', 'destructive', 'outline', 'secondary', 'ghost', 'link'] as const
    variants.forEach(variant => {
      const { unmount } = render(<Button variant={variant}>{variant}</Button>)
      expect(screen.getByText(variant)).toBeDefined()
      unmount()
    })
  })

  it('renders with all sizes', () => {
    const sizes = ['default', 'sm', 'lg', 'icon'] as const
    sizes.forEach(size => {
      const { unmount } = render(<Button size={size}>btn</Button>)
      unmount()
    })
  })

  it('passes disabled prop', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByText('Disabled')).toBeDisabled()
  })

  it('passes onClick handler', () => {
    let clicked = false
    render(<Button onClick={() => { clicked = true }}>Go</Button>)
    screen.getByText('Go').click()
    expect(clicked).toBe(true)
  })
})

describe('Card component', () => {
  it('renders Card with all sub-components', () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Title</CardTitle>
          <CardDescription>Description</CardDescription>
        </CardHeader>
        <CardContent>Content</CardContent>
        <CardFooter>Footer</CardFooter>
      </Card>
    )
    expect(screen.getByText('Title')).toBeDefined()
    expect(screen.getByText('Description')).toBeDefined()
    expect(screen.getByText('Content')).toBeDefined()
    expect(screen.getByText('Footer')).toBeDefined()
  })

  it('applies custom className to Card', () => {
    const { container } = render(<Card className="my-card">Test</Card>)
    expect(container.firstChild).toHaveClass('my-card')
  })
})
