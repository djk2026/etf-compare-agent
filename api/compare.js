/**
 * POST /api/compare — Vercel Serverless Function
 * 代理 Dify Workflow API（streaming 模式），隐藏 API Key
 */
export default async function handler(req, res) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  const { codes } = req.body || {};
  if (!codes || typeof codes !== 'string' || !codes.trim()) {
    return res.status(400).json({ error: '请输入 ETF 代码，例如：510300,159915' });
  }

  const DIFY_API_KEY = process.env.DIFY_API_KEY;
  if (!DIFY_API_KEY) {
    return res.status(500).json({ error: '服务配置错误：未设置 API Key' });
  }

  try {
    const response = await fetch('https://api.dify.ai/v1/workflows/run', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${DIFY_API_KEY}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        inputs: { codes: codes.trim() },
        response_mode: 'streaming',
        user: 'web-user',
      }),
    });

    if (!response.ok) {
      const errText = await response.text().catch(() => '');
      console.error('Dify API error:', response.status, errText);
      return res.status(502).json({ error: `比对服务异常 (${response.status})，请稍后重试` });
    }

    // 逐块读取 Dify SSE 流
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let report = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const event = JSON.parse(line.slice(6));
            if (event.event === 'workflow_finished') {
              const outputs = event.data?.outputs || {};
              report = outputs.report || outputs.text || '';
            }
          } catch (_) {
            // 跳过非 JSON 或格式异常的行
          }
        }
      }
    }

    return res.json({ report: report || '暂无分析结果' });
  } catch (err) {
    console.error('Proxy error:', err);
    return res.status(500).json({ error: '网络异常，比对服务暂时不可用，请稍后重试' });
  }
}
