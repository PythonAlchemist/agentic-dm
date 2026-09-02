import type { Metadata } from 'next'
import { Geist, Geist_Mono, Literata } from 'next/font/google'
import './globals.css'

const geistSans = Geist({ variable: '--font-geist-sans', subsets: ['latin'] })
const geistMono = Geist_Mono({ variable: '--font-geist-mono', subsets: ['latin'] })

// THE BOOK'S OWN VOICE. Literata is a variable face with an optical-size axis,
// commissioned for reading published books on screens -- and here it does a
// second job: it is a provenance channel. Where the words are the book's, the
// face is the serif; everything the app says is Geist. A reader who cannot use
// the hues at all still sees which is which.
const literata = Literata({
  variable: '--font-literata',
  subsets: ['latin'],
  style: ['normal', 'italic'],
})

export const metadata: Metadata = {
  // THE PRODUCT'S NAME, NOT THE INSTRUMENT'S. Players will read this tab. The
  // lab still exists and is still called that, at `/lab`.
  title: 'Table',
  description:
    'Run your game from the book, and always know which part is the book.',
}

export default function RootLayout({ children }: LayoutProps<'/'>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${literata.variable} h-full antialiased`}
    >
      {/* Fixed height rather than min-height: the lab is an app-shaped page
          with its own scrolling regions -- the transcript and the working set
          scroll independently -- and a body that grows would put a second
          scrollbar around the whole thing. */}
      <body className="h-full">{children}</body>
    </html>
  )
}
