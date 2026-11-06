# Domain Glossary

This glossary defines ubiquitous domain concepts and architectural seams for OccAIsion.

## Core Domain Concepts

### Draft
The central listing aggregate. Represents an item being prepared for multi-platform sale across Swiss (Ricardo, Tutti) and German (eBay DE, Kleinanzeigen) marketplaces. A Draft contains identified product information, user notes, status, pricing analysis, platform-specific listing payloads, and an ordered collection of image assets.

### DraftStore
The deep module responsible for draft lifecycle persistence, asset file storage, image variant caching, and import/export backups. It presents a single unified interface to callers and isolates disk layout, variant generation, and atomic rollbacks behind its seam.

### Image Asset & Variants
Visual media associated with a Draft. Every uploaded image is automatically cleaned of EXIF/GPS metadata and stored alongside generated variants:
- **Optimized**: Auto-contrasted, RGB, downscaled to <= 2048px for display.
- **AI**: Downscaled to <= 1024px to preserve token efficiency and privacy during multimodal model inference.
- **Cutout**: Subject isolated via background removal onto a neutral studio canvas (#F8F9FA).
- **Blurred**: Subject isolated with Gaussian-blurred original background for aesthetic emphasis.

### Market Source
An external pricing channel (e.g. eBay DE completed listings, Kleinanzeigen, Idealo, Ricardo, Tutti, Toppreise, Digitec/Galaxus) queried to determine market price ranges and competitive offer recommendations.
