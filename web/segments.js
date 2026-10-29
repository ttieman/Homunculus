// Text for the Segment physics panel: one line per segment.
export function formatSegments(list) {
  if (!list.length) return 'No segments.';
  return list
    .map(
      s =>
        s.id +
        ': ' +
        s.start.toFixed(2) +
        '–' +
        s.end.toFixed(2) +
        ' s' +
        ('strength' in s ? ' · strength ' + s.strength : '') +
        ('damping' in s ? ' · damping ' + s.damping : '') +
        (s.blend ? ' · blend ' + s.blend + ' s ' + s.curve : ''),
    )
    .join('\n');
}
