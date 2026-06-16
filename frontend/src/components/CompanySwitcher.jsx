/**
 * CompanySwitcher —— 头部公司切换器（占位接线）
 *
 * 落 00b 页面4「公司切换器」+ 总览 §9.3「用户-公司-角色三元授权」：
 *  - 多公司用户在「已开通公司」间切换 active_company_id；read-privileged 可选「全部（汇总）」
 *
 * ⚠️ 后端现状（不在本次前端壳范围，记 TODO）：
 *  - 引擎 `UserCompanyAccess` 已建表+seed，但 `_company_filter` 从不读它＝死代码（引擎 05 D-05c）；
 *  - 无「切换 active_company_id」端点、会话也不载 active_company_id（auth.py /me 只回单 company_id）。
 *  → 本组件为前端占位：从 /api/query(company) 取可见公司列表，active_company_id 暂存 localStorage，
 *    切换后广播事件让页面重取。真正生效需后端 ➕扩展：接线 UserCompanyAccess + 会话载 active_company_id
 *    + _company_filter 改读授权公司集（EXT-00b-B，必入 engineFlags）。
 */

import { useEffect, useState } from 'react';
import { Select, Tooltip } from 'antd';
import { BankOutlined } from '@ant-design/icons';
import { query } from '../api';
import { useAuth } from '../auth';

const LS_KEY = 'pt_active_company_id';

export function getActiveCompanyId() {
  const v = localStorage.getItem(LS_KEY);
  return v ? Number(v) : null;
}

export default function CompanySwitcher() {
  const { user } = useAuth();
  const [companies, setCompanies] = useState([]);
  const [active, setActive] = useState(getActiveCompanyId() || user?.company_id || null);

  useEffect(() => {
    let alive = true;
    // 占位：拉 company 表（__queryable__）。后端接线后应改拉「我已开通的公司集」端点。
    query('company', { limit: 100 })
      .then((r) => {
        if (!alive) return;
        // /api/query 返回 { table, data:[...], count, total }
        const rows = (r.data?.data || []).filter((c) => c.is_active !== false);
        setCompanies(rows);
      })
      .catch(() => setCompanies([]));
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (active == null && user?.company_id) setActive(user.company_id);
  }, [user, active]);

  const onChange = (val) => {
    setActive(val);
    localStorage.setItem(LS_KEY, String(val));
    // 广播：让工作台/台账随 active_company_id 重取（后端生效前为前端约定）
    window.dispatchEvent(new CustomEvent('pt:company-changed', { detail: { companyId: val } }));
  };

  const options = companies.map((c) => ({
    value: c.id,
    label: c.short_name || c.name || c.code,
  }));

  return (
    <Tooltip title="切换公司（占位：后端切换端点待接线）" placement="bottom">
      <Select
        size="small"
        variant="filled"
        value={active}
        onChange={onChange}
        options={options}
        placeholder="选择公司"
        suffixIcon={<BankOutlined />}
        style={{ minWidth: 150 }}
        popupMatchSelectWidth={false}
      />
    </Tooltip>
  );
}
