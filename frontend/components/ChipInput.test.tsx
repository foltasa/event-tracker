import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChipInput from './ChipInput'

describe('ChipInput', () => {
  it('commits a chip on Enter', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, 'the beatles{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(['the beatles'])
  })

  it('preserves spaces and commas inside a chip', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, 'die sterne, hamburg{Enter}')
    expect(onChange).toHaveBeenLastCalledWith(['die sterne, hamburg'])
  })

  it('dedupes case-insensitively on commit', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={['Radiohead']} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, 'radiohead{Enter}')
    // No new chip committed → onChange either not called with a longer array, or called with the same array.
    for (const call of onChange.mock.calls) {
      expect(call[0]).toEqual(['Radiohead'])
    }
  })

  it('ignores empty and whitespace-only commits', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={[]} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.type(input, '   {Enter}')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('removes the last chip on Backspace when input is empty', async () => {
    const onChange = vi.fn()
    render(<ChipInput value={['a', 'b']} onChange={onChange} placeholder="type…" />)
    const input = screen.getByPlaceholderText('type…')
    await userEvent.click(input)
    await userEvent.keyboard('{Backspace}')
    expect(onChange).toHaveBeenLastCalledWith(['a'])
  })

  it('renders existing chips', () => {
    render(<ChipInput value={['a', 'b']} onChange={() => {}} placeholder="type…" />)
    expect(screen.getByText('a')).toBeInTheDocument()
    expect(screen.getByText('b')).toBeInTheDocument()
  })
})
