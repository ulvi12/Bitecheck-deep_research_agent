"""Generic, source-text-bound nutrition panels; no brand or product records."""
import re

CORE_FIELDS=('energy_kcal','total_fat_g','carbohydrates_g','sugars_g','saturated_fat_g','sodium_mg','protein_g')
PATTERNS={
 'added_sugars_g':r'added\s+sugars?|zugesetzte.*zucker|sucre[s]?\s+ajout|az[uú]cares?\s+a[nñ]adidos',
 'saturated_fat_g':r'saturat|ges[aä]ttigt|\bsaturi\b|\bsaturés?\b|verzadigd',
 'total_fat_g':r'total\s+fat|\bfat\b|\bfett\b|\bgrassi\b|mati[eè]res\s+grasses|\bgrasas\b|\bvetten\b',
 'carbohydrates_g':r'carbohydrat|kohlenhydrat|carboidrati|glucides?|hidratos|koolhydrat',
 'sugars_g':r'total\s+sugars?|\bsugars?\b|\bzucker\b|\bzuccheri\b|\bsucres?\b|az[uú]cares?|\bsuikers\b',
 'sodium_mg':r'\bsodium\b|\bnatrium\b|\bsodio\b',
 'salt_g':r'\bsalt\b|\bsalz\b|\bsale\b|\bsel\b|\bsal\b|\bzout\b',
 'protein_g':r'\bprotein|\beiwei[ßs]|\bprot[eé]in|\bproteine',
 'fiber_g':r'\bfib(?:er|re|ra)|ballaststoff|\bvezel',
 'energy_kcal':r'\bcalories\b|\benergy\b|\benergie\b|\benergia\b|\benerg[ií]a\b|\bénergie\b',
}
NUMBER=r'(?<![\d.,])\d+(?:[.,]\d+)?'
BASIS=re.compile(r'(?:per\s+100\s*(g|ml)\b|(?:serving\s*size|portion\s*size|portionsgr[oö][ßs]e|valori\s+medi|durchschnittswerte|pro\s+|per\s+|porci[oó]n|portie|pour\s+|je\s+)[^\n]{0,65}?(\d+(?:[.,]\d+)?)\s*(g|ml)\b)',re.I)

def number(text):return float(text.replace(',','.'))

def extract_panels(content):
    lines=[re.sub(r'(?<=[A-Za-zÀ-ÿ])(?=\d)',' ',re.sub(r'[ \t]+',' ',s)).strip(' |\t') for s in str(content).splitlines()]
    panels=[];current=None;pending=[]
    def finish():
        nonlocal current
        if current and len(current['nutrients'])>=2:
            signature=(current['basis_amount'],current['basis_unit'],tuple(sorted(current['nutrients'].items())))
            if not any(p['_signature']==signature and p['context']==current['context'] for p in panels):
                current['_signature']=signature;panels.append(current)
        current=None
    for i,line in enumerate(lines):
        basis=BASIS.search(line)
        if basis:
            if basis.group(1):amount,unit=100.0,basis.group(1).lower()
            else:amount,unit=number(basis.group(2)),basis.group(3).lower()
            # Exclude reference-intake text and recipe serving sizes. A panel
            # still needs multiple actual nutrient declarations below it.
            if 'reference' not in line.lower() and amount>0:
                if current and current['nutrients']:finish();pending=[]
                candidate={'basis_amount':amount,'basis_unit':unit,'basis_quote':line,
                           'context':'\n'.join(lines[max(0,i-4):i+1])[-600:],
                           'nutrients':{},'declarations':{}}
                pending.append(candidate)
                if current is None:current=candidate
            continue
        if not current:continue
        if re.search(r'\btrans\b|transfet',line,re.I):continue
        # Ignore daily-value percentages and do not turn a '<1 g' declaration
        # or 'not a significant source' sentence into an exact measurement.
        if re.search(r'less\s+than|not\s+a\s+significant|moins\s+de|weniger\s+als|[<≤]',line,re.I):continue
        field=next((key for key,pattern in PATTERNS.items() if re.search(pattern,line,re.I)),None)
        if not field:continue
        if field=='energy_kcal':
            match=re.search('('+NUMBER+r')\s*kcal\b',line,re.I)
            if not match and re.search(r'calories',line,re.I):match=re.search('('+NUMBER+')',line,re.I)
            if not match:continue
            value=number(match.group(1))
        else:
            match=re.search('('+NUMBER+r')\s*(mg|g)\b',line,re.I)
            if not match:continue
            value=number(match.group(1));unit=match.group(2).lower()
            if field=='sodium_mg' and unit!='mg':continue
            if field!='sodium_mg' and unit!='g':continue
        if field in current['nutrients']:
            # Responsive pages sometimes put all basis headings ahead of all
            # columns. Associate the next repeated nutrient block with the
            # next declared basis; never mix per-serving and per-100 values.
            previous=current
            finish()
            if pending and pending[0] is previous:pending.pop(0)
            if not pending:continue
            current=pending[0]
        current['nutrients'][field]=value;current['declarations'][field]=line
    finish()
    return [{k:v for k,v in panel.items() if k!='_signature'} for panel in panels]
