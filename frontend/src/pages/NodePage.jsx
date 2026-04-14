/**
 * 通用节点页面 — 如果转换规则有custom_html就渲染它，否则用通用组件
 * 这个组件可以在WorkflowActions里以Modal方式弹出
 */

import { useEffect, useRef } from 'react';

export default function NodePage({ customHtml, data, onSubmit }) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (!customHtml || !containerRef.current) return;
    containerRef.current.innerHTML = customHtml;

    // 注入数据到HTML模板
    const fillField = (id, value) => {
      const el = containerRef.current.querySelector(`#${id}`);
      if (el) {
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
          el.value = value ?? '';
        } else {
          el.textContent = value ?? '';
        }
      }
    };

    if (data) {
      Object.entries(data).forEach(([k, v]) => fillField(k, v));
    }

    // 绑定提交按钮
    const submitBtn = containerRef.current.querySelector('[data-action="submit"]');
    if (submitBtn && onSubmit) {
      submitBtn.addEventListener('click', () => {
        // 收集所有input的值
        const inputs = containerRef.current.querySelectorAll('input, textarea, select');
        const values = {};
        inputs.forEach(el => { if (el.name) values[el.name] = el.value; });
        onSubmit(values);
      });
    }
  }, [customHtml, data]);

  if (!customHtml) return null;
  return <div ref={containerRef} />;
}
