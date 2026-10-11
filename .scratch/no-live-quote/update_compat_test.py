from pathlib import Path
p=Path('frontend/lib/__tests__/tradeCardOverride.test.ts')
s=p.read_text(encoding='utf-8')
s=s.replace("it('returns the card unchanged when the pick matches the auto-picked contract', () => {", "it('preserves the card data and copies liveness when the pick matches the auto-picked contract', () => {")
s=s.replace('    expect(applyPickedContract(card, picked)).toBe(card);', '    expect(applyPickedContract(card, picked)).toEqual({ ...card, noLiveQuote: false });\n    expect(applyPickedContract(card, { ...picked, noLiveQuote: true })).toEqual({ ...card, noLiveQuote: true });')
p.write_text(s,encoding='utf-8')
