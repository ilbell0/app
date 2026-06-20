import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity, Modal, TextInput } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useLanguage } from '@/src/context/LanguageContext';
import { NothingTheme } from '@/src/theme/NothingTheme';
import { COUNTER_ENGINE, FORMATIONS } from '@/src/data';
import PitchDiagram from './PitchDiagram';

const POS: Record<string, string[]> = {};
(FORMATIONS as any[]).forEach((f) => { POS[f.name] = f.positions; });

type Level = 'forte' | 'pari' | 'debole';

interface Props {
  visible: boolean;
  onClose: () => void;
}

/** Flusso guidato: avversario -> livello rosa -> setup completo del counter. */
export default function CounterWizard({ visible, onClose }: Props) {
  const insets = useSafeAreaInsets();
  const { language } = useLanguage();
  const isIt = language === 'it';
  const [step, setStep] = useState(1);
  const [search, setSearch] = useState('');
  const [av, setAv] = useState<any | null>(null);
  const [level, setLevel] = useState<Level | null>(null);

  const reset = () => { setStep(1); setSearch(''); setAv(null); setLevel(null); };
  const close = () => { reset(); onClose(); };

  const qDigits = search.replace(/\D/g, '');
  const list = useMemo(() => {
    const all = COUNTER_ENGINE as any[];
    if (!search.trim()) return all;
    return all.filter((e) =>
      e.av.toLowerCase().includes(search.toLowerCase().trim()) ||
      (qDigits.length > 0 && e.av.replace(/\D/g, '').includes(qDigits))
    );
  }, [search, qDigits]);

  const scenario = av && level ? av[level] : null;
  const arrowColor = (a: string) => (a === '↑' ? '#FFFFFF' : a === '↓' ? NothingTheme.colors.accent : NothingTheme.colors.textTertiary);

  return (
    <Modal animationType="slide" transparent visible={visible} onRequestClose={close}>
      <View style={[styles.overlay, { paddingTop: insets.top + 10 }]}>
        {/* Header */}
        <View style={styles.header}>
          {step > 1 && (
            <TouchableOpacity style={styles.iconBtn} onPress={() => setStep(step - 1)}>
              <Ionicons name="arrow-back" size={22} color={NothingTheme.colors.textPrimary} />
            </TouchableOpacity>
          )}
          <Text style={styles.title}>{isIt ? 'TROVA COUNTER' : 'FIND COUNTER'}</Text>
          <TouchableOpacity style={[styles.iconBtn, styles.iconBtnRight]} onPress={close}>
            <Ionicons name="close" size={24} color={NothingTheme.colors.textPrimary} />
          </TouchableOpacity>
        </View>

        {/* Step indicator */}
        <View style={styles.steps}>
          {[1, 2, 3].map((n) => (
            <View key={n} style={[styles.stepDot, step >= n && styles.stepDotActive]} />
          ))}
        </View>

        <View style={styles.divider} />

        {/* STEP 1 — avversario */}
        {step === 1 && (
          <>
            <Text style={styles.stepLabel}>{isIt ? '1 · MODULO AVVERSARIO' : '1 · OPPONENT FORMATION'}</Text>
            <View style={styles.searchRow}>
              <Ionicons name="search" size={16} color={NothingTheme.colors.textTertiary} />
              <TextInput
                style={styles.searchInput}
                value={search}
                onChangeText={setSearch}
                placeholder={isIt ? 'Cerca (es. 3-3-2-2)' : 'Search (e.g. 3-3-2-2)'}
                placeholderTextColor={NothingTheme.colors.textTertiary}
                autoCapitalize="none"
                autoCorrect={false}
              />
            </View>
            <ScrollView style={styles.flex} contentContainerStyle={styles.listPad} showsVerticalScrollIndicator={false}>
              {list.map((e, i) => (
                <TouchableOpacity key={i} style={styles.row} onPress={() => { setAv(e); setStep(2); }} activeOpacity={0.7}>
                  <Text style={styles.rowText}>{e.av}</Text>
                  <Ionicons name="chevron-forward" size={18} color={NothingTheme.colors.textTertiary} />
                </TouchableOpacity>
              ))}
            </ScrollView>
          </>
        )}

        {/* STEP 2 — livello */}
        {step === 2 && (
          <View style={styles.flex}>
            <Text style={styles.stepLabel}>{isIt ? '2 · IL TUO LIVELLO' : '2 · YOUR LEVEL'}</Text>
            <Text style={styles.vsLine}>{isIt ? 'Contro' : 'Against'} <Text style={styles.vsName}>{av?.av}</Text></Text>
            {([
              ['debole', isIt ? 'Sono più forte' : 'I am stronger', isIt ? 'Attacca e domina' : 'Attack and dominate'],
              ['pari', isIt ? 'Pari livello' : 'Equal level', isIt ? 'Gioco equilibrato' : 'Balanced game'],
              ['forte', isIt ? 'Sono più debole' : 'I am weaker', isIt ? 'Difendi e riparti' : 'Defend and counter'],
            ] as [Level, string, string][]).map(([lv, t, sub]) => (
              <TouchableOpacity key={lv} style={styles.levelBtn} onPress={() => { setLevel(lv); setStep(3); }} activeOpacity={0.8}>
                <View style={styles.flex}>
                  <Text style={styles.levelTitle}>{t}</Text>
                  <Text style={styles.levelSub}>{sub}</Text>
                </View>
                <Ionicons name="chevron-forward" size={20} color={NothingTheme.colors.textTertiary} />
              </TouchableOpacity>
            ))}
          </View>
        )}

        {/* STEP 3 — risultato */}
        {step === 3 && scenario && (
          <ScrollView style={styles.flex} contentContainerStyle={styles.resultPad} showsVerticalScrollIndicator={false}>
            <Text style={styles.resultVs}>{isIt ? 'CONTRO' : 'VS'} {av.av}</Text>
            <View style={styles.formationBox}>
              <Text style={styles.formationName}>{scenario.mod}</Text>
              {scenario.alt && scenario.alt !== scenario.mod && (
                <Text style={styles.altName}>{isIt ? 'Alternativa' : 'Alternative'}: {scenario.alt}</Text>
              )}
            </View>
            {POS[scenario.mod] && (
              <View style={styles.pitchWrap}>
                <PitchDiagram positions={POS[scenario.mod]} arrows={scenario.fr} />
              </View>
            )}
            <View style={styles.grid}>
              {[
                [isIt ? 'Mentalità' : 'Mentality', scenario.men],
                [isIt ? 'Passaggi' : 'Passing', scenario.pass],
                [isIt ? 'Stile' : 'Style', scenario.stile],
                ['Pressing', scenario.press],
                [isIt ? 'Marcatura' : 'Marking', scenario.marc],
                [isIt ? 'Contrasti' : 'Tackling', scenario.cont],
                [isIt ? 'Contropiede' : 'Counter', scenario.ctrl],
                [isIt ? 'Fuorigioco' : 'Offside', scenario.fuo],
              ].map(([k, v]) => (
                <View key={k} style={styles.gridRow}>
                  <Text style={styles.gridK}>{k}</Text>
                  <Text style={styles.gridV}>{v}</Text>
                </View>
              ))}
            </View>
            <View style={styles.tipBox}><Text style={styles.tipText}>{scenario.w}</Text></View>
            <TouchableOpacity style={styles.restartBtn} onPress={reset} activeOpacity={0.8}>
              <Ionicons name="refresh" size={16} color={NothingTheme.colors.accent} />
              <Text style={styles.restartText}>{isIt ? 'NUOVA RICERCA' : 'NEW SEARCH'}</Text>
            </TouchableOpacity>
          </ScrollView>
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: NothingTheme.colors.background },
  flex: { flex: 1 },
  header: { paddingHorizontal: 24, paddingBottom: 16, alignItems: 'center', justifyContent: 'center' },
  title: { color: NothingTheme.colors.textPrimary, fontSize: 18, fontWeight: '700', letterSpacing: 2 },
  iconBtn: { position: 'absolute', left: 24, top: -4, width: 40, height: 40, borderRadius: 20, backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border, alignItems: 'center', justifyContent: 'center', zIndex: 1 },
  iconBtnRight: { left: undefined, right: 24 },
  steps: { flexDirection: 'row', justifyContent: 'center', gap: 8, paddingBottom: 14 },
  stepDot: { width: 24, height: 4, borderRadius: 2, backgroundColor: NothingTheme.colors.border },
  stepDotActive: { backgroundColor: NothingTheme.colors.accent },
  divider: { height: 1, backgroundColor: NothingTheme.colors.divider },
  stepLabel: { color: NothingTheme.colors.textSecondary, fontSize: 10, fontWeight: '700', letterSpacing: 2, paddingHorizontal: 24, paddingTop: 18, paddingBottom: 12 },
  searchRow: { flexDirection: 'row', alignItems: 'center', gap: 8, marginHorizontal: 24, paddingHorizontal: 14, paddingVertical: 10, borderRadius: 8, backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border },
  searchInput: { flex: 1, color: NothingTheme.colors.textPrimary, fontSize: 14, padding: 0 },
  listPad: { padding: 24, paddingTop: 12, paddingBottom: 60 },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', backgroundColor: NothingTheme.colors.surface, borderRadius: 8, padding: 16, marginBottom: 8, borderWidth: 1, borderColor: NothingTheme.colors.border },
  rowText: { color: NothingTheme.colors.textPrimary, fontSize: 15, fontWeight: '600' },
  vsLine: { color: NothingTheme.colors.textTertiary, fontSize: 14, paddingHorizontal: 24, marginBottom: 16 },
  vsName: { color: NothingTheme.colors.accent, fontWeight: '700' },
  levelBtn: { flexDirection: 'row', alignItems: 'center', marginHorizontal: 24, marginBottom: 12, padding: 18, borderRadius: 8, backgroundColor: NothingTheme.colors.surface, borderWidth: 1, borderColor: NothingTheme.colors.border },
  levelTitle: { color: NothingTheme.colors.textPrimary, fontSize: 16, fontWeight: '700' },
  levelSub: { color: NothingTheme.colors.textTertiary, fontSize: 12, marginTop: 2 },
  resultPad: { padding: 24, paddingBottom: 60 },
  resultVs: { color: NothingTheme.colors.textTertiary, fontSize: 11, fontWeight: '700', letterSpacing: 2, marginBottom: 12 },
  formationBox: { backgroundColor: NothingTheme.colors.surface, borderRadius: 8, padding: 20, alignItems: 'center', borderWidth: 1, borderColor: NothingTheme.colors.border, marginBottom: 16 },
  formationName: { color: NothingTheme.colors.textPrimary, fontSize: 26, fontWeight: '700', letterSpacing: 1 },
  altName: { color: NothingTheme.colors.textTertiary, fontSize: 12, marginTop: 6 },
  pitchWrap: { marginBottom: 16 },
  grid: { backgroundColor: NothingTheme.colors.surface, borderRadius: 8, borderWidth: 1, borderColor: NothingTheme.colors.border, overflow: 'hidden', marginBottom: 16 },
  gridRow: { flexDirection: 'row', justifyContent: 'space-between', padding: 14, borderBottomWidth: 1, borderBottomColor: NothingTheme.colors.border },
  gridK: { color: NothingTheme.colors.textTertiary, fontSize: 12 },
  gridV: { color: NothingTheme.colors.textPrimary, fontSize: 12, fontWeight: '600' },
  tipBox: { backgroundColor: NothingTheme.colors.surface, borderRadius: 8, padding: 16, borderWidth: 1, borderColor: NothingTheme.colors.border, borderLeftWidth: 3, borderLeftColor: NothingTheme.colors.accent, marginBottom: 20 },
  tipText: { color: NothingTheme.colors.textSecondary, fontSize: 13, lineHeight: 20 },
  restartBtn: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8, padding: 14, borderRadius: 8, borderWidth: 1, borderColor: NothingTheme.colors.accent },
  restartText: { color: NothingTheme.colors.accent, fontSize: 12, fontWeight: '700', letterSpacing: 1 },
});
