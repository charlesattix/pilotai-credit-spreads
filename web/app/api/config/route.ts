import { NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'
import yaml from 'js-yaml'

export async function GET() {
  try {
    const configPath = path.join(process.cwd(), '../config.yaml')
    const data = await fs.readFile(configPath, 'utf-8')
    const config = yaml.load(data)
    return NextResponse.json(config)
  } catch (error) {
    console.error('Failed to read config:', error)
    return NextResponse.json({ error: 'Failed to read config' }, { status: 500 })
  }
}

export async function POST(request: Request) {
  try {
    const config = await request.json()
    const configPath = path.join(process.cwd(), '../config.yaml')
    const yamlStr = yaml.dump(config)
    await fs.writeFile(configPath, yamlStr, 'utf-8')
    return NextResponse.json({ success: true })
  } catch (error) {
    console.error('Failed to write config:', error)
    return NextResponse.json({ error: 'Failed to write config' }, { status: 500 })
  }
}
