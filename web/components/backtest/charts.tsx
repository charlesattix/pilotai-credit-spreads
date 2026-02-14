'use client'

import { formatCurrency } from '@/lib/utils'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'

interface BacktestResult {
  winning_trades: number
  losing_trades: number
  equity_curve: Array<{ date: string; equity: number }>
  trade_distribution: Array<{ range: string; count: number }>
}

export default function BacktestCharts({ results }: { results: BacktestResult }) {
  if (!results) return null

  return (
    <div className="space-y-6">
      {results.equity_curve && results.equity_curve.length > 0 && (
        <div className="bg-white rounded-lg border border-border p-6">
          <h3 className="text-lg font-semibold mb-4">Equity Curve</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={results.equity_curve}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="date" stroke="#6B7280" />
              <YAxis stroke="#6B7280" />
              <Tooltip
                contentStyle={{ backgroundColor: '#fff', border: '1px solid #E5E7EB', borderRadius: '8px' }}
                formatter={(value: number | string) => formatCurrency(Number(value))}
              />
              <Legend />
              <Line type="monotone" dataKey="equity" stroke="#9B6DFF" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        {results.trade_distribution && results.trade_distribution.length > 0 && (
          <div className="bg-white rounded-lg border border-border p-6">
            <h3 className="text-lg font-semibold mb-4">Trade Distribution</h3>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={results.trade_distribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
                <XAxis dataKey="range" stroke="#6B7280" />
                <YAxis stroke="#6B7280" />
                <Tooltip contentStyle={{ backgroundColor: '#fff', border: '1px solid #E5E7EB', borderRadius: '8px' }} />
                <Bar dataKey="count" fill="#9B6DFF" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {(results.winning_trades > 0 || results.losing_trades > 0) && (
          <div className="bg-white rounded-lg border border-border p-6">
            <h3 className="text-lg font-semibold mb-4">Win/Loss Distribution</h3>
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={[
                    { name: 'Wins', value: results.winning_trades },
                    { name: 'Losses', value: results.losing_trades },
                  ]}
                  cx="50%" cy="50%"
                  labelLine={false}
                  label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                  outerRadius={80}
                  dataKey="value"
                >
                  <Cell fill="#10B981" />
                  <Cell fill="#EF4444" />
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}
