/* Keep existing chart data/options while using the workspace's readable colors. */
(function () {
  'use strict';
  const charts = new Set();
  const colorKeys = new Set(['color', 'borderColor', 'backgroundColor', 'areaColor', 'shadowColor']);
  const brandColors = {
    '#517a28': '--primary', '#3a5a1e': '--primary', '#16a34a': '--success',
    '#15803d': '--success', '#22c55e': '--success', '#b88620': '--gold',
    '#f59e0b': '--warning', '#d97706': '--warning', '#b91c1c': '--danger',
    '#dc2626': '--danger', '#ef4444': '--danger', '#2563eb': '--info',
    '#0284c7': '--info', '#2e5c8a': '--info', '#0f766e': '--cyan',
    '#0891b2': '--cyan', '#6d28d9': '--violet', '#7c3aed': '--violet',
    '#8b5cf6': '--violet', '#64748b': '--muted'
  };
  function themed(option) {
    const css = getComputedStyle(document.documentElement);
    const value = token => css.getPropertyValue(token).trim();
    function copy(item, key) {
      if (typeof item === 'string' && colorKeys.has(key) && brandColors[item.toLowerCase()]) return value(brandColors[item.toLowerCase()]);
      if (Array.isArray(item)) return item.map(child => copy(child, key));
      if (item && Object.getPrototypeOf(item) === Object.prototype) {
        return Object.fromEntries(Object.entries(item).map(([childKey, child]) => [childKey, copy(child, childKey)]));
      }
      return item;
    }
    const result = copy(option);
    result.backgroundColor = 'transparent';
    result.color = result.color || ['--primary', '--gold', '--info', '--violet', '--cyan', '--danger'].map(value);
    result.textStyle = { ...result.textStyle, color: value('--text-2'), fontFamily: value('--font-body') };
    if (result.legend) {
      const styleLegend = legend => ({ ...legend, textStyle: { ...legend.textStyle, color: value('--text-2') } });
      result.legend = Array.isArray(result.legend) ? result.legend.map(styleLegend) : styleLegend(result.legend);
    }
    if (result.tooltip) {
      result.tooltip = { ...result.tooltip, backgroundColor: value('--panel-strong'), borderColor: value('--border'),
        textStyle: { ...result.tooltip.textStyle, color: value('--text') } };
    }
    for (const name of ['xAxis', 'yAxis']) {
      if (!result[name]) continue;
      const styleAxis = axis => ({ ...axis,
        axisLabel: { ...axis.axisLabel, color: value('--muted') },
        nameTextStyle: { ...axis.nameTextStyle, color: value('--muted') },
        axisLine: { ...axis.axisLine, lineStyle: { ...axis.axisLine?.lineStyle, color: value('--border') } },
        splitLine: { ...axis.splitLine, lineStyle: { ...axis.splitLine?.lineStyle, color: value('--border-soft') } }
      });
      result[name] = Array.isArray(result[name]) ? result[name].map(styleAxis) : styleAxis(result[name]);
    }
    const styleSeries = series => ({ ...series, label: { ...series.label, color: value('--text-2') } });
    if (result.series) result.series = Array.isArray(result.series) ? result.series.map(styleSeries) : styleSeries(result.series);
    return result;
  }
  window.SikaCharts = {
    init(element, theme, options) {
      const chart = window.echarts.init(element, theme, options);
      const setOption = chart.setOption.bind(chart);
      const history = [];
      chart.setOption = function (option, settings) {
        if (settings === true || settings?.notMerge) history.length = 0;
        history.push({ option, settings });
        setOption(themed(option), settings);
      };
      charts.add({ chart, history, setOption });
      return chart;
    }
  };
  window.addEventListener('sf:themechange', () => {
    charts.forEach(entry => {
      if (entry.chart.isDisposed()) { charts.delete(entry); return; }
      entry.history.forEach(({ option, settings }) => entry.setOption(themed(option), settings));
    });
  });
})();
