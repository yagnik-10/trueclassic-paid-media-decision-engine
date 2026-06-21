// Brand/platform logos are served as static assets from /public/logos so every
// surface uses the same authentic marks (Meta + Google brand SVGs, the real
// True Classic wordmark) instead of duplicated inline paths.

const PLATFORM_SRC: Record<string, string> = {
  meta: '/logos/meta.svg',
  google: '/logos/google.svg',
  shopify: '/logos/shopify.svg',
};

const PLATFORM_LABEL: Record<string, string> = {
  meta: 'Meta',
  google: 'Google',
  shopify: 'Shopify',
};

export function PlatformLogo({
  platform,
  className = 'w-4 h-4',
}: {
  platform: string;
  className?: string;
}) {
  const src = PLATFORM_SRC[platform];
  if (!src) return <span className={`inline-block rounded-full bg-gray-400 ${className}`} />;
  return (
    <img
      src={src}
      alt={`${PLATFORM_LABEL[platform] ?? platform} logo`}
      className={`${className} shrink-0 object-contain`}
      draggable={false}
    />
  );
}

export function TrueClassicWordmark({ className = 'h-4' }: { className?: string }) {
  return (
    <img
      src="/logos/true-classic-wordmark.svg"
      alt="True Classic"
      className={`${className} w-auto max-w-full object-contain`}
      draggable={false}
    />
  );
}
