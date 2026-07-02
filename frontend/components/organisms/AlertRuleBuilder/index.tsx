'use client';
import { useState } from 'react';
import { useChartStore } from '@/lib/chartStore';
import { useChartAlertStore } from '@/lib/chartAlertStore';
import { Text } from '@/components/primitives';
import type { Condition, ConditionOperator, AlertRule, LogicOperator, PriceCondition, IndicatorCondition, StructureCondition, RegimeCondition, RegimeState, RegimeModel } from '@/types/alerts';
import type { SignalKind } from '@/types/structure';
import styles from './AlertRuleBuilder.module.css';

interface Props {
  onClose: () => void;
  editRule?: AlertRule | null;
  duplicateFrom?: AlertRule | null;
  prefill?: { price: number } | null;
}

const OPERATORS: { value: ConditionOperator; label: string }[] = [
  { value: '>', label: '>' },
  { value: '<', label: '<' },
  { value: '>=', label: '>=' },
  { value: '<=', label: '<=' },
  { value: 'crosses_above', label: 'crosses above' },
  { value: 'crosses_below', label: 'crosses below' },
];

const STRUCTURE_KINDS: SignalKind[] = ['FVG', 'BOS', 'CHoCH', 'OrderBlock', 'Divergence'];

const DIRECTIONS = [
  { value: '', label: 'any' },
  { value: 'bullish', label: 'bullish' },
  { value: 'bearish', label: 'bearish' },
];

const REGIME_STATES_OMM: RegimeState[] = ['any', 'Bull', 'Bear', 'Choppy'];
const REGIME_STATES_HMM: RegimeState[] = ['any', 'Bull', 'Bear', 'Sideways', 'Trending', 'Choppy', 'Mean-reverting'];
const REGIME_MODELS: RegimeModel[] = ['any', 'OMM', 'HMM'];

function emptyPriceCondition(): PriceCondition {
  return { kind: 'price', operator: '>', value: 0 };
}

function emptyIndicatorCondition(): IndicatorCondition {
  return { kind: 'indicator', indicator: '', operator: '>', value: 0 };
}

function emptyStructureCondition(): StructureCondition {
  return { kind: 'structure', signal_kind: 'BOS' };
}

function emptyRegimeCondition(): RegimeCondition {
  return { kind: 'regime', model: 'OMM', state: 'Bull' };
}

function makeId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

export default function AlertRuleBuilder({ onClose, editRule, duplicateFrom, prefill }: Props) {
  const { symbol: chartSymbol, interval: chartInterval, activeIndicators } = useChartStore();
  const { addRule, updateRule } = useChartAlertStore();
  const seed = editRule ?? duplicateFrom ?? null;
  const symbol = seed?.symbol ?? chartSymbol;
  const interval = seed?.interval ?? chartInterval;
  const [name, setName] = useState(seed?.name ?? '');
  const [conditions, setConditions] = useState<Condition[]>(
    seed?.group.conditions
    ?? (prefill ? [{ kind: 'price', operator: 'crosses_above', value: prefill.price } as PriceCondition] : [emptyPriceCondition()]),
  );
  const [logic, setLogic] = useState<LogicOperator>(seed?.group.logic ?? 'AND');
  const [nOfMThreshold, setNOfMThreshold] = useState(seed?.group.n_of_m_threshold ?? 1);
  const [cooldown, setCooldown] = useState(seed?.cooldown_minutes ?? 60);
  const [expiryType, setExpiryType] = useState<'never' | 'custom'>(
    seed?.expiry_date ? 'custom' : 'never',
  );
  const [expiryDate, setExpiryDate] = useState(seed?.expiry_date ?? '');
  const [error, setError] = useState('');

  const indicatorOptions = activeIndicators.map((i) => ({
    value: i.id,
    label: `${i.type}(${Object.values(i.params).join(',') || 'default'})`,
  }));

  const updateCondition = (idx: number, patch: Partial<Condition>) => {
    setConditions((c) => c.map((cond, i) => (i === idx ? { ...cond, ...patch } as Condition : cond)));
  };

  const removeCondition = (idx: number) => {
    if (conditions.length <= 1) return;
    setConditions((c) => c.filter((_, i) => i !== idx));
  };

  const addCondition = (kind: 'price' | 'indicator' | 'structure' | 'regime') => {
    if (kind === 'price') setConditions((c) => [...c, emptyPriceCondition()]);
    if (kind === 'indicator') setConditions((c) => [...c, emptyIndicatorCondition()]);
    if (kind === 'structure') setConditions((c) => [...c, emptyStructureCondition()]);
    if (kind === 'regime') setConditions((c) => [...c, emptyRegimeCondition()]);
  };

  const handleSave = () => {
    if (!name.trim()) {
      setError('Name is required');
      return;
    }
    setError('');
    const rule: AlertRule = {
      id: editRule?.id ?? makeId(),
      name: name.trim(),
      symbol,
      interval,
      enabled: editRule?.enabled ?? true,
      group: { logic, conditions, n_of_m_threshold: logic === 'N_OF_M' ? nOfMThreshold : undefined },
      cooldown_minutes: cooldown,
      expiry_date: expiryType === 'custom' && expiryDate ? expiryDate : null,
      created_at: editRule?.created_at ?? new Date().toISOString(),
      last_triggered_at: editRule?.last_triggered_at ?? null,
    };
    if (editRule) {
      const existingRules = useChartAlertStore.getState().rules;
      const collision = existingRules.some(
        (r) =>
          r.id !== editRule.id &&
          r.symbol === symbol &&
          r.interval === interval &&
          JSON.stringify(r.group.conditions) === JSON.stringify(conditions),
      );
      if (collision) {
        setError('Another rule with these conditions already exists');
        return;
      }
      updateRule(editRule.id, rule);
    } else {
      const added = addRule(rule);
      if (!added) {
        setError('A rule with these conditions already exists');
        return;
      }
    }
    onClose();
  };

  return (
    <div className={styles.panel}>
      <div className={styles.header}>
        <Text size={13} tone="primary" weight={500}>
          {editRule ? 'Edit Alert' : 'New Alert'}
        </Text>
        <button className={styles.close} onClick={onClose} aria-label="Close">
          &times;
        </button>
      </div>

      <div className={styles.body}>
        <label className={styles.field}>
          <Text size={11} tone="secondary">Name</Text>
          <input
            className={styles.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. AAPL breakout"
          />
        </label>

        <div className={styles.meta}>
          <Text size={11} tone="dim">Symbol: {symbol}</Text>
          <Text size={11} tone="dim">Interval: {interval}</Text>
        </div>

        <div className={styles.logicToggle}>
          <Text size={11} tone="secondary">When</Text>
          <div className={styles.logicBtns}>
            <button
              className={`${styles.logicBtn} ${logic === 'AND' ? styles.logicActive : ''}`}
              onClick={() => setLogic('AND')}
            >
              ALL
            </button>
            <button
              className={`${styles.logicBtn} ${logic === 'OR' ? styles.logicActive : ''}`}
              onClick={() => setLogic('OR')}
            >
              ANY
            </button>
            <button
              className={`${styles.logicBtn} ${logic === 'N_OF_M' ? styles.logicActive : ''}`}
              onClick={() => setLogic('N_OF_M')}
            >
              N of M
            </button>
          </div>
          {logic === 'N_OF_M' ? (
            <span className={styles.nOfMRow}>
              <input
                className={styles.numInput}
                type="number"
                min={1}
                max={conditions.length}
                value={nOfMThreshold}
                onChange={(e) => setNOfMThreshold(Math.max(1, Math.min(conditions.length, Number(e.target.value))))}
                style={{ width: 40 }}
              />
              <Text size={11} tone="dim">of {conditions.length} conditions met</Text>
            </span>
          ) : (
            <Text size={11} tone="dim">conditions are met</Text>
          )}
        </div>

        <div className={styles.conditions}>
          {conditions.map((c, idx) => (
            <div key={idx} className={styles.conditionRow}>
              <select
                className={styles.select}
                value={c.kind}
                onChange={(e) => {
                  const k = e.target.value as 'price' | 'indicator' | 'structure' | 'regime';
                  if (k === 'price') updateCondition(idx, emptyPriceCondition());
                  if (k === 'indicator') updateCondition(idx, emptyIndicatorCondition());
                  if (k === 'structure') updateCondition(idx, emptyStructureCondition());
                  if (k === 'regime') updateCondition(idx, emptyRegimeCondition());
                }}
              >
                <option value="price">Price</option>
                <option value="indicator">Indicator</option>
                <option value="structure">Structure</option>
                <option value="regime">Regime (OMM/HMM)</option>
              </select>

              {c.kind === 'price' && (
                <>
                  <select
                    className={styles.select}
                    value={c.operator}
                    onChange={(e) => updateCondition(idx, { operator: e.target.value as ConditionOperator })}
                  >
                    {OPERATORS.filter((o) => !o.value.includes('crosses')).map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    step="0.01"
                    value={c.value}
                    onChange={(e) => updateCondition(idx, { value: Number(e.target.value) })}
                  />
                </>
              )}

              {c.kind === 'indicator' && (
                <>
                  <select
                    className={styles.select}
                    value={c.indicator}
                    onChange={(e) => updateCondition(idx, { indicator: e.target.value })}
                  >
                    <option value="">Select...</option>
                    {indicatorOptions.map((o) => (
                      <option key={o.value} value={o.label}>{o.label}</option>
                    ))}
                  </select>
                  <select
                    className={styles.select}
                    value={c.operator}
                    onChange={(e) => updateCondition(idx, { operator: e.target.value as ConditionOperator })}
                  >
                    {OPERATORS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    step="0.01"
                    value={c.value}
                    onChange={(e) => updateCondition(idx, { value: Number(e.target.value) })}
                  />
                </>
              )}

              {c.kind === 'structure' && (
                <>
                  <select
                    className={styles.select}
                    value={c.signal_kind}
                    onChange={(e) => updateCondition(idx, { signal_kind: e.target.value as SignalKind })}
                  >
                    {STRUCTURE_KINDS.map((k) => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                  <select
                    className={styles.select}
                    value={c.direction ?? ''}
                    onChange={(e) => updateCondition(idx, { direction: (e.target.value || undefined) as 'bullish' | 'bearish' | undefined })}
                  >
                    {DIRECTIONS.map((d) => (
                      <option key={d.value} value={d.value}>{d.label}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    min={0}
                    max={100}
                    placeholder="Conf%"
                    value={c.min_confidence ?? ''}
                    onChange={(e) =>
                      updateCondition(idx, {
                        min_confidence: e.target.value ? Number(e.target.value) : undefined,
                      })
                    }
                  />
                </>
              )}

              {c.kind === 'regime' && (
                <>
                  <select
                    className={styles.select}
                    value={c.model}
                    onChange={(e) => {
                      const newModel = e.target.value as RegimeModel;
                      const validStates: readonly RegimeState[] = newModel === 'OMM' ? REGIME_STATES_OMM : REGIME_STATES_HMM;
                      const prev = conditions[idx];
                      const prevState = prev.kind === 'regime' ? prev.state : 'any';
                      const nextState: RegimeState = (validStates as readonly string[]).includes(prevState) ? prevState as RegimeState : 'any';
                      updateCondition(idx, { model: newModel, state: nextState });
                    }}
                  >
                    {REGIME_MODELS.map((m) => (
                      <option key={m} value={m}>{m === 'any' ? 'any model' : m}</option>
                    ))}
                  </select>
                  <select
                    className={styles.select}
                    value={c.state}
                    onChange={(e) => updateCondition(idx, { state: e.target.value as RegimeState })}
                  >
                    {(c.model === 'OMM' ? REGIME_STATES_OMM : REGIME_STATES_HMM).map((s) => (
                      <option key={s} value={s}>{s === 'any' ? 'any state' : s}</option>
                    ))}
                  </select>
                  <input
                    className={styles.numInput}
                    type="number"
                    min={0}
                    max={100}
                    placeholder="Conv%"
                    value={c.min_conviction ?? ''}
                    onChange={(e) =>
                      updateCondition(idx, {
                        min_conviction: e.target.value ? Number(e.target.value) : undefined,
                      })
                    }
                  />
                </>
              )}

              {conditions.length > 1 && (
                <button
                  className={styles.removeBtn}
                  onClick={() => removeCondition(idx)}
                  aria-label="Remove condition"
                >
                  &times;
                </button>
              )}
            </div>
          ))}
        </div>

        <div className={styles.addRow}>
          <button className={styles.addBtn} onClick={() => addCondition('price')}>
            + Price
          </button>
          <button className={styles.addBtn} onClick={() => addCondition('indicator')}>
            + Indicator
          </button>
          <button className={styles.addBtn} onClick={() => addCondition('structure')}>
            + Structure
          </button>
          <button className={styles.addBtn} onClick={() => addCondition('regime')}>
            + Regime
          </button>
        </div>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Cooldown (minutes)</Text>
          <input
            className={styles.numInput}
            type="number"
            min={1}
            max={1440}
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
          />
        </label>

        <label className={styles.field}>
          <Text size={11} tone="secondary">Expires</Text>
          <select
            className={styles.select}
            value={expiryType}
            onChange={(e) => setExpiryType(e.target.value as 'never' | 'custom')}
          >
            <option value="never">Never</option>
            <option value="custom">Custom date</option>
          </select>
          {expiryType === 'custom' && (
            <input
              className={styles.input}
              type="date"
              value={expiryDate}
              onChange={(e) => setExpiryDate(e.target.value)}
            />
          )}
        </label>

        {error && <Text size={11} tone="reject">{error}</Text>}
      </div>

      <div className={styles.footer}>
        <button className={styles.cancelBtn} onClick={onClose}>Cancel</button>
        <button className={styles.saveBtn} onClick={handleSave}>
          {editRule ? 'Save' : 'Create Alert'}
        </button>
      </div>
    </div>
  );
}
