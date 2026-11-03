import "../../patterns/companies/company-logo.css";
import { useState } from "react";
import { CompanyIcon, hasBrandIcon } from "../../ui";

// Company mark, in preference order: bundled brand mark -> the profile's
// remote logo -> a brand-coloured monogram.
//
// The bundled mark leads because `logoUrl` points at a third-party host: it is
// a network round-trip per company, it can 404, and on a page listing every
// tracked company it is a request per row to someone else's host. Remote stays
// as the middle rung so a company the bundled set does not carry still shows
// its real logo.
export function CompanyLogo({
  slug,
  name,
  logoUrl,
  brandColor,
  size = 40,
}: {
  slug: string;
  name: string;
  logoUrl: string | null;
  brandColor: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  // `hasBrandIcon`, not `resolveBrandIcon`: a company added by careers URL has a
  // mark in a lazy shard, and asking only the bundled set would show the remote
  // logo for one frame and then swap it out.
  const mark = hasBrandIcon(slug, name);
  const showImage = !mark && logoUrl && !failed;

  if (mark || !showImage) {
    return (
      <span className="company-logo company-logo-mark" style={{ width: size, height: size }}>
        <CompanyIcon
          slug={slug}
          display={name}
          size={Math.round(size * 0.72)}
          brand
          fallbackColor={brandColor}
        />
      </span>
    );
  }

  return (
    <span
      className="company-logo has-img"
      style={{
        width: size,
        height: size,
        background: brandColor ? `${brandColor}22` : "var(--app-surface-subtle)",
        borderColor: brandColor ?? "var(--app-border)",
      }}
      aria-hidden="true"
    >
      <img src={logoUrl!} alt="" loading="lazy" onError={() => setFailed(true)} />
    </span>
  );
}
