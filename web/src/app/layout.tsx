import type { Metadata } from 'next'
import { Geist, Geist_Mono } from 'next/font/google'
import './globals.css'

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] })
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Agent Lab',
  description: 'Grounded answers from the Curse of Strahd canon graph, with their provenance.',
}

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      {/* Fixed height rather than min-height: the lab is an app-shaped page
          with its own scrolling regions -- the transcript and the working set
          scroll independently -- and a body that grows would put a second
          scrollbar around the whole thing. */}
      <body className="h-full bg-neutral-950 text-neutral-200">{children}</body>
    </html>
  )
}
