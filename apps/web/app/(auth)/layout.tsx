import Image from "next/image";
import Link from "next/link";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen bg-white font-sans text-ink">
      {/* Left brand panel */}
      <aside className="relative hidden w-[42%] overflow-hidden bg-ink lg:flex">
        {/* Gradient orbs — softer */}
        <div className="pointer-events-none absolute inset-0">
          <div className="absolute -left-32 -top-32 h-[500px] w-[500px] rounded-full bg-deep-violet/40 blur-[140px]" />
          <div className="absolute -bottom-40 right-0 h-[450px] w-[450px] rounded-full bg-magenta/25 blur-[120px]" />
          <div className="absolute bottom-1/3 left-1/3 h-[300px] w-[300px] rounded-full bg-coral/15 blur-[100px]" />
        </div>

        <div className="relative z-10 flex flex-1 flex-col p-10 xl:p-12">
          {/* Logo */}
          <Link href="https://sayvors.com" className="mb-12 inline-flex w-fit items-center gap-2.5 opacity-90 transition-opacity hover:opacity-100">
            <Image src="/Sayvors_Icon.png" alt="" width={36} height={26} className="h-6 w-auto" />
            <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={130} height={22} className="h-5 w-auto" />
          </Link>

          {/* Illustration */}
          <div className="mb-auto flex justify-center">
            <div className="relative w-full max-w-sm">
              <div className="absolute inset-0 rounded-3xl bg-gradient-to-br from-white/8 to-transparent blur-xl" />
              <Image
                src="/undraw-chatting.svg"
                alt=""
                width={800}
                height={670}
                loading="eager"
                priority
                sizes="(max-width: 1024px) 0px, 42vw"
                className="relative h-auto w-full drop-shadow-2xl transition-transform duration-500 hover:scale-[1.02]"
              />
            </div>
          </div>

          {/* Tagline */}
          <div className="mt-auto">
            <h1 className="text-[2rem] font-bold leading-[1.15] tracking-tight text-white">
              One Voice.<br />One Line.
            </h1>
            <p className="mt-3 max-w-xs text-[14px] leading-relaxed text-white/50">
              The customer platform built for modern teams.
            </p>
          </div>
        </div>
      </aside>

      {/* Right form area */}
      <main className="relative flex flex-1 items-center justify-center px-6 py-10">
        {/* Back link */}
        <Link
          href="https://sayvors.com"
          className="absolute left-6 top-6 z-10 inline-flex items-center gap-1.5 text-[13px] font-medium text-ink/30 transition-colors duration-200 hover:text-ink/60"
        >
          <svg viewBox="0 0 16 16" fill="currentColor" className="h-3.5 w-3.5 transition-transform duration-200 group-hover:-translate-x-0.5">
            <path fillRule="evenodd" d="M12 8a.75.75 0 01-.75.75H5.56l2.22 2.22a.75.75 0 11-1.06 1.06l-3.5-3.5a.75.75 0 010-1.06l3.5-3.5a.75.75 0 011.06 1.06L5.56 7.25h5.69A.75.75 0 0112 8z" clipRule="evenodd" />
          </svg>
          Home
        </Link>

        {/* Mobile logo */}
        <div className="absolute left-6 top-6 flex items-center gap-2 lg:hidden">
          <Image src="/Sayvors_Icon.png" alt="" width={28} height={20} className="h-5 w-auto" />
          <Image src="/Sayvors_Wordmark_Light.png" alt="Sayvors" width={100} height={17} className="h-4 w-auto" />
        </div>

        <div className="w-full max-w-[380px]">
          {children}
        </div>
      </main>
    </div>
  );
}
