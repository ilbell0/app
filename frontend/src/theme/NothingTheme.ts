/**
 * Nothing Design System Theme
 * Inspired by Nothing OS - Minimalist, Dot Matrix, High Contrast
 */

export const NothingTheme = {
  // Core Colors
  colors: {
    // Backgrounds
    background: '#000000',        // Pure black (OLED optimized)
    backgroundAlt: '#0D0D0D',     // Slightly lighter black
    surface: '#141414',           // Card/surface background
    surfaceAlt: '#1A1A1A',        // Elevated surface
    
    // Text
    textPrimary: '#FFFFFF',       // Primary text
    textSecondary: '#ABABAB',     // Secondary text
    textTertiary: '#666666',      // Muted text
    textDisabled: '#444444',      // Disabled text
    
    // Accent - Nothing Red
    accent: '#D71921',            // Primary accent (Nothing Red)
    accentLight: '#FF2D36',       // Lighter accent for hover
    accentDark: '#A31419',        // Darker accent
    accentMuted: 'rgba(215, 25, 33, 0.15)', // Muted accent background
    
    // Functional Colors
    success: '#FFFFFF',           // Success (white in Nothing style)
    warning: '#D71921',           // Warning (red)
    error: '#D71921',             // Error (red)
    info: '#ABABAB',              // Info (gray)
    
    // Borders & Dividers
    border: '#2A2A2A',            // Subtle border
    borderLight: '#1F1F1F',       // Lighter border
    divider: '#1A1A1A',           // Divider line
    
    // Dot Matrix Effect
    dotActive: '#D71921',         // Active dot (red)
    dotInactive: '#333333',       // Inactive dot
  },
  
  // Typography
  typography: {
    // Font families (monospace for Nothing aesthetic)
    fontFamily: {
      primary: 'System',          // System font (fallback)
      mono: 'Courier',            // Monospace for dot-matrix feel
    },
    
    // Font sizes
    sizes: {
      xs: 10,
      sm: 12,
      base: 14,
      md: 16,
      lg: 20,
      xl: 24,
      xxl: 32,
      hero: 40,
    },
    
    // Font weights
    weights: {
      light: '300',
      regular: '400',
      medium: '500',
      semibold: '600',
      bold: '700',
    },
    
    // Line heights
    lineHeights: {
      tight: 1.2,
      normal: 1.5,
      relaxed: 1.8,
    },
    
    // Letter spacing (wider for Nothing style)
    letterSpacing: {
      tight: -0.5,
      normal: 0,
      wide: 0.5,
      wider: 1,
      widest: 2,
    },
  },
  
  // Spacing (8pt grid)
  spacing: {
    xs: 4,
    sm: 8,
    md: 12,
    base: 16,
    lg: 20,
    xl: 24,
    xxl: 32,
    xxxl: 48,
  },
  
  // Border radius
  radius: {
    none: 0,
    sm: 4,
    md: 8,
    lg: 12,
    xl: 16,
    full: 9999,
  },
  
  // Shadows (minimal for Nothing style)
  shadows: {
    none: {
      shadowColor: 'transparent',
      shadowOffset: { width: 0, height: 0 },
      shadowOpacity: 0,
      shadowRadius: 0,
      elevation: 0,
    },
    subtle: {
      shadowColor: '#000',
      shadowOffset: { width: 0, height: 2 },
      shadowOpacity: 0.3,
      shadowRadius: 4,
      elevation: 2,
    },
  },
};

// Common styles using Nothing theme
export const NothingStyles = {
  // Container styles
  container: {
    flex: 1,
    backgroundColor: NothingTheme.colors.background,
  },
  
  // Text styles
  textHero: {
    color: NothingTheme.colors.textPrimary,
    fontSize: NothingTheme.typography.sizes.hero,
    fontWeight: NothingTheme.typography.weights.bold,
    letterSpacing: NothingTheme.typography.letterSpacing.tight,
  },
  
  textTitle: {
    color: NothingTheme.colors.textPrimary,
    fontSize: NothingTheme.typography.sizes.xxl,
    fontWeight: NothingTheme.typography.weights.bold,
    letterSpacing: NothingTheme.typography.letterSpacing.tight,
  },
  
  textHeading: {
    color: NothingTheme.colors.textPrimary,
    fontSize: NothingTheme.typography.sizes.xl,
    fontWeight: NothingTheme.typography.weights.semibold,
  },
  
  textSubheading: {
    color: NothingTheme.colors.textSecondary,
    fontSize: NothingTheme.typography.sizes.md,
    fontWeight: NothingTheme.typography.weights.medium,
    letterSpacing: NothingTheme.typography.letterSpacing.wide,
    textTransform: 'uppercase',
  },
  
  textBody: {
    color: NothingTheme.colors.textPrimary,
    fontSize: NothingTheme.typography.sizes.base,
    fontWeight: NothingTheme.typography.weights.regular,
    lineHeight: NothingTheme.typography.sizes.base * NothingTheme.typography.lineHeights.normal,
  },
  
  textCaption: {
    color: NothingTheme.colors.textSecondary,
    fontSize: NothingTheme.typography.sizes.sm,
    fontWeight: NothingTheme.typography.weights.regular,
  },
  
  textMono: {
    color: NothingTheme.colors.textPrimary,
    fontSize: NothingTheme.typography.sizes.sm,
    fontFamily: NothingTheme.typography.fontFamily.mono,
    letterSpacing: NothingTheme.typography.letterSpacing.wider,
  },
  
  // Card styles
  card: {
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: NothingTheme.radius.lg,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    padding: NothingTheme.spacing.base,
  },
  
  cardElevated: {
    backgroundColor: NothingTheme.colors.surfaceAlt,
    borderRadius: NothingTheme.radius.lg,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    padding: NothingTheme.spacing.base,
  },
  
  // Button styles
  buttonPrimary: {
    backgroundColor: NothingTheme.colors.accent,
    borderRadius: NothingTheme.radius.md,
    paddingVertical: NothingTheme.spacing.md,
    paddingHorizontal: NothingTheme.spacing.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  buttonOutline: {
    backgroundColor: 'transparent',
    borderRadius: NothingTheme.radius.md,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    paddingVertical: NothingTheme.spacing.md,
    paddingHorizontal: NothingTheme.spacing.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  buttonGhost: {
    backgroundColor: 'transparent',
    paddingVertical: NothingTheme.spacing.sm,
    paddingHorizontal: NothingTheme.spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
  },
  
  // Badge styles
  badge: {
    backgroundColor: NothingTheme.colors.accentMuted,
    borderRadius: NothingTheme.radius.sm,
    paddingVertical: NothingTheme.spacing.xs,
    paddingHorizontal: NothingTheme.spacing.sm,
  },
  
  badgeText: {
    color: NothingTheme.colors.accent,
    fontSize: NothingTheme.typography.sizes.xs,
    fontWeight: NothingTheme.typography.weights.semibold,
    textTransform: 'uppercase',
    letterSpacing: NothingTheme.typography.letterSpacing.wider,
  },
  
  // Divider
  divider: {
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
  },
  
  // Icon container
  iconContainer: {
    width: 48,
    height: 48,
    borderRadius: NothingTheme.radius.md,
    backgroundColor: NothingTheme.colors.surface,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
};

export default NothingTheme;
