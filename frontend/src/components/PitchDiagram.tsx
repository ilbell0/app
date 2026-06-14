import React, { useMemo } from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { NothingTheme } from '@/src/theme/NothingTheme';

/**
 * Mini-campo che disegna una formazione dalle sue posizioni (offline, niente SVG).
 * Stile Nothing: campo scuro, giocatori come pallini, frecce per i movimenti.
 *
 * positions: es. ['GK','DL','DC','DC','DR','MC','MC','AML','AMC','AMR','ST']
 * arrows:    es. { DL: '↓', AML: '↑' } (opzionale, dallo scenario selezionato)
 */

type Arrows = Record<string, string>;

// fascia verticale di ogni linea (0 = alto/attacco, 1 = basso/porta)
const ROW_Y: Record<string, number> = {
  GK: 0.9,
  DEF: 0.74,   // DL DC DR
  DMC: 0.6,
  MID: 0.46,   // ML MC MR
  AM: 0.29,    // AML AMC AMR
  ST: 0.11,
};

// a quale linea appartiene ogni codice posizione
const ROW_OF: Record<string, keyof typeof ROW_Y> = {
  GK: 'GK',
  DL: 'DEF', DC: 'DEF', DR: 'DEF',
  DML: 'DMC', DMC: 'DMC', DMR: 'DMC',
  ML: 'MID', MC: 'MID', MR: 'MID',
  AML: 'AM', AMC: 'AM', AMR: 'AM',
  ST: 'ST',
};

// peso orizzontale: sinistra < centro < destra (per ordinare la riga)
const SIDE_WEIGHT: Record<string, number> = {
  DL: 0, DML: 0, ML: 0, AML: 0,
  GK: 2, DC: 2, DMC: 2, MC: 2, AMC: 2, ST: 2,
  DR: 4, DMR: 4, MR: 4, AMR: 4,
};

interface PlacedPlayer {
  pos: string;
  x: number; // 0..1
  y: number; // 0..1
  arrow?: string;
}

function layout(positions: string[]): PlacedPlayer[] {
  // raggruppa per linea conservando l'ordine d'ingresso
  const byRow: Record<string, { pos: string; order: number }[]> = {};
  positions.forEach((pos, order) => {
    const row = ROW_OF[pos];
    if (!row) return;
    (byRow[row] ||= []).push({ pos, order });
  });

  const placed: PlacedPlayer[] = [];
  Object.entries(byRow).forEach(([row, players]) => {
    // ordina sinistra->destra, stabile sui pari
    const sorted = [...players].sort(
      (a, b) => (SIDE_WEIGHT[a.pos] - SIDE_WEIGHT[b.pos]) || (a.order - b.order)
    );
    const n = sorted.length;
    sorted.forEach((p, i) => {
      placed.push({ pos: p.pos, x: (i + 1) / (n + 1), y: ROW_Y[row as keyof typeof ROW_Y] });
    });
  });
  return placed;
}

interface Props {
  positions: string[];
  arrows?: Arrows;
  height?: number;
}

export default function PitchDiagram({ positions, arrows, height = 240 }: Props) {
  const players = useMemo(() => layout(positions), [positions]);
  const DOT = 30;

  return (
    <View style={[styles.pitch, { height }]}>
      {/* linee del campo: metà campo + cerchio centrale, minimali */}
      <View style={styles.halfLine} />
      <View style={styles.centerCircle} />
      <View style={styles.penaltyBox} />

      {players.map((p, idx) => {
        const arrow = arrows?.[p.pos];
        const isUp = arrow === '↑';
        const isDown = arrow === '↓';
        return (
          <View
            key={`${p.pos}-${idx}`}
            style={[
              styles.dotWrap,
              {
                left: `${p.x * 100}%`,
                top: `${p.y * 100}%`,
                marginLeft: -DOT / 2,
                marginTop: -DOT / 2,
              },
            ]}
          >
            <View
              style={[
                styles.dot,
                { width: DOT, height: DOT, borderRadius: DOT / 2 },
                isUp && styles.dotUp,
                isDown && styles.dotDown,
              ]}
            >
              <Text style={styles.dotText}>{p.pos}</Text>
            </View>
            {arrow && arrow !== '—' && (
              <Text style={[styles.arrow, isDown ? styles.arrowDown : styles.arrowUp]}>{arrow}</Text>
            )}
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  pitch: {
    width: '100%',
    backgroundColor: NothingTheme.colors.surface,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: NothingTheme.colors.border,
    position: 'relative',
    overflow: 'hidden',
  },
  halfLine: {
    position: 'absolute',
    top: '50%',
    left: 0,
    right: 0,
    height: 1,
    backgroundColor: NothingTheme.colors.divider,
  },
  centerCircle: {
    position: 'absolute',
    top: '50%',
    left: '50%',
    width: 60,
    height: 60,
    borderRadius: 30,
    borderWidth: 1,
    borderColor: NothingTheme.colors.divider,
    marginLeft: -30,
    marginTop: -30,
  },
  penaltyBox: {
    position: 'absolute',
    bottom: 0,
    left: '50%',
    width: 90,
    height: 34,
    borderWidth: 1,
    borderBottomWidth: 0,
    borderColor: NothingTheme.colors.divider,
    marginLeft: -45,
  },
  dotWrap: {
    position: 'absolute',
    alignItems: 'center',
  },
  dot: {
    backgroundColor: NothingTheme.colors.background,
    borderWidth: 1.5,
    borderColor: NothingTheme.colors.textTertiary,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotUp: {
    borderColor: '#FFFFFF',
  },
  dotDown: {
    borderColor: NothingTheme.colors.accent,
  },
  dotText: {
    color: NothingTheme.colors.textPrimary,
    fontSize: 8,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  arrow: {
    position: 'absolute',
    top: -12,
    fontSize: 13,
    fontWeight: '700',
  },
  arrowUp: {
    color: '#FFFFFF',
  },
  arrowDown: {
    color: NothingTheme.colors.accent,
  },
});
