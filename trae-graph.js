// Converts a Trae .design document into the GRAPH shape this viewer draws.
// Pages stay where Trae wrote them; htmlSrc is resolved against the design file's directory.
function traeToGraph(doc) {
  const replaced = {
    'page-home': 'page-home-add-theatre',
    'page-home-layout': 'page-home-add-theatre',
    'page-menu': 'page-menu-layout'
  };
  const colors = ['#657b79', '#506964', '#8a7460', '#3d6b8a', '#6d5b7b'];
  const pages = (doc && Array.isArray(doc.data) ? doc.data : []).filter(function (page) {
    return page && page.type === 'page' && page.devMetadata && page.devMetadata.htmlSrc;
  });
  const nodes = pages.map(function (page, index) {
    const canvas = page.canvasData || {};
    const htmlSrc = String(page.devMetadata.htmlSrc).replace(/\\/g, '/').replace(/^\/+/, '');
    if (!htmlSrc || htmlSrc.split('/').indexOf('..') !== -1) return null;
    const fileName = htmlSrc.split('/').pop();
    return {
      id: page.id,
      label: page.title || page.id,
      sublabel: fileName,
      page: htmlSrc,
      x: Number(canvas.x) || 0,
      y: Number(canvas.y) || 0,
      color: colors[index % colors.length],
      desc: page.title || page.id
    };
  }).filter(Boolean);
  const ids = {};
  nodes.forEach(function (node) { ids[node.id] = true; });
  const edges = [];
  const seen = {};
  pages.forEach(function (page) {
    const interactions = page.devMetadata.interactions || [];
    interactions.forEach(function (interaction) {
      if (!interaction || interaction.hideEdge) return;
      let target = interaction.targetPageId;
      if (!ids[target] && replaced[target] && ids[replaced[target]]) target = replaced[target];
      if (!ids[target] || target === page.id) return;
      const key = page.id + '\0' + target;
      if (seen[key]) return;
      seen[key] = true;
      edges.push({
        from: page.id,
        to: target,
        label: interaction.transitionLabel || interaction.domId || ''
      });
    });
  });
  return { nodes: nodes, edges: edges };
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { traeToGraph: traeToGraph };
}
