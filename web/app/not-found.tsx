import Link from 'next/link'

export default function NotFound() {
  return (
    <div className="flex items-center justify-center min-h-[50vh]">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">404</h1>
        <p className="text-muted-foreground mb-4">Page not found</p>
        <Link href="/" className="text-brand-purple hover:underline text-sm font-medium">
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
