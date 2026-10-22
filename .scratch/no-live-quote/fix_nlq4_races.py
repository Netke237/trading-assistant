from pathlib import Path
root=Path.cwd()
page=root/'frontend/app/(frame)/screener/step-7-trade-card/page.tsx'
original=page.read_bytes()
(root/'.scratch/no-live-quote/nlq4-round1-page.bin').write_bytes(original)
source=original.decode('utf-8',errors='surrogateescape').replace('\r\n','\n')
(root/'.scratch/no-live-quote/nlq4-round1-page.txt').write_bytes(source.encode('utf-8',errors='surrogateescape'))
changes=[
("  const [quoteConfirmation, setQuoteConfirmation] = useState<{ contractKey: string } | null>(null);", "  const [quoteConfirmation, setQuoteConfirmation] = useState<{ contractKey: string } | null>(null);\n  const quoteConfirmationRef = useRef<{ contractKey: string } | null>(null);\n  const quoteRequestGenerationRef = useRef(0);\n  const updateQuoteConfirmation = (confirmation: { contractKey: string } | null) => {\n    quoteConfirmationRef.current = confirmation;\n    setQuoteConfirmation(confirmation);\n  };"),
("  if (currentContractKeyRef.current !== contractKey) selectionEpochRef.current += 1;", "  if (currentContractKeyRef.current !== contractKey) {\n    selectionEpochRef.current += 1;\n    quoteConfirmationRef.current = null;\n  }"),
("  useEffect(() => { setQuoteConfirmation(null); }, [contractKey]);", "  useEffect(() => { updateQuoteConfirmation(null); }, [contractKey]);"),
("    const keyAtRequest = contractKey;", "    const keyAtRequest = contractKey;\n    const quoteGeneration = ++quoteRequestGenerationRef.current;"),
("          setLiveQuote(q ? { ...q, key: keyAtRequest } : null);", "          // A send-time probe owns the quote display over an older card-open fetch.\n          if (quoteGeneration === quoteRequestGenerationRef.current) {\n            setLiveQuote(q ? { ...q, key: keyAtRequest } : null);\n          }"),
("      const quoteController = new AbortController();", "      const quoteGeneration = ++quoteRequestGenerationRef.current;\n      const quoteController = new AbortController();"),
("      setLiveQuote(freshQuote ? { ...freshQuote, key: keyAtSend } : null);", "      if (quoteGeneration === quoteRequestGenerationRef.current) {\n        setLiveQuote(freshQuote ? { ...freshQuote, key: keyAtSend } : null);\n      }"),
("freshQuote?.quoteLive !== true && quoteConfirmation?.contractKey !== keyAtSend", "freshQuote?.quoteLive !== true && quoteConfirmationRef.current?.contractKey !== keyAtSend"),
("onChange={(e) => setQuoteConfirmation(e.target.checked && contractKey ? { contractKey } : null)}", "onChange={(e) => updateQuoteConfirmation(e.target.checked && contractKey ? { contractKey } : null)}"),
]
for old,new in changes:
    assert source.count(old)==1,(old,source.count(old))
    source=source.replace(old,new)
page.write_bytes(source.encode('utf-8',errors='surrogateescape'))
test=root/'frontend/app/(frame)/screener/step-7-trade-card/__tests__/no-live-quote.test.tsx'
repro=(root/'.scratch/no-live-quote/nlq4-audit1-race-repro.test.tsx').read_text(encoding='utf-8',errors='surrogateescape')
extra=repro[repro.index("it('audit: an old open-time quote"):]
test.write_text(test.read_text(encoding='utf-8',errors='surrogateescape')+'\n'+extra,encoding='utf-8',errors='surrogateescape')
